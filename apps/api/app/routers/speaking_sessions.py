"""Maszyna stanów sesji (spec §3, §4, dodatek v2): 6 faz, jeden SourcePack
powtarzany 4 razy w bloku głównym, Chunk Drill Banku A/B, sonda transferowa.

Fazy 0/1 (rozgrzewka czytania, wejście z tekstem) nie mają stanu po stronie
serwera - to czysta prezentacja seed_text/guiding_questions, klient je
wyświetla z odpowiedzi /start. Faza 0 korzysta z istniejącego /api/reading.
"""

import json
import logging
import random

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import db_session, get_db
from ..models import (
    Attempt,
    Chunk,
    ChunkExposure,
    Domain,
    FluencyMetrics,
    KeywordPlan,
    Round,
    SelfTranscription,
    SourcePack,
    SpeakingSession,
    TransferProbe,
    WritingRehearsal,
    now_iso,
)
from ..services import attempt_pipeline, chunk_scheduler, domains as domains_svc, pack_gen, support, transfer_probe as transfer_probe_svc
from ..services.constants import KEYWORD_PLAN_MAX_ITEMS, KEYWORD_PLAN_MAX_WORDS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/speaking-sessions", tags=["speaking-sessions"])

LEVEL_PREP_S = {4: 60, 3: 30, 2: 15, 1: 10, 0: 0}
# rundy główne jako kompresja pomysłu, nie wytrzymałość (spec zmian §4.1) -
# ten sam czas dla wszystkich poziomów wsparcia, celowo bez wariantu
# 60/45/30/30 dla bardzo niskiego wsparcia (jeszcze nie implementowany)
COMPRESSION_SPEAK_S = [90, 75, 60, 45]
WRITING_REHEARSAL_MIN_CEILING = 3
MIN_R3_INTERRUPT_PHONATION_FACTOR = 0.6

# Keyword Planning (spec zmian §3): czas na zapisanie haseł maleje z
# poziomem wsparcia, przy 0 nie ma jawnego planowania w ogóle
KEYWORD_PLANNING_S = {4: 45, 3: 30, 2: 15, 1: 5, 0: 0}


def _round_plan(ceiling: int) -> list[dict]:
    plan = []
    for i in range(4):
        level = max(0, ceiling - i)
        plan.append(
            {
                "number": i + 1,
                "support_level": level,
                "prep_s": LEVEL_PREP_S[level],
                "speak_limit_s": COMPRESSION_SPEAK_S[i],
            }
        )
    return plan


def _fm_dict(fm: FluencyMetrics | None) -> dict | None:
    if fm is None:
        return None
    out = {
        "articulation_rate": fm.articulation_rate,
        "mean_length_of_run": fm.mean_length_of_run,
        "phonation_time_ratio": fm.phonation_time_ratio,
        "mid_clause_pause_duration": fm.mid_clause_pause_duration,
        "mid_clause_pause_frequency": fm.mid_clause_pause_frequency,
        "clause_final_pause_duration": fm.clause_final_pause_duration,
        "clause_final_pause_frequency": fm.clause_final_pause_frequency,
        "filled_pause_rate": fm.filled_pause_rate,
        "ttfw": fm.ttfw,
        "clause_segmentation_confidence": fm.clause_segmentation_confidence,
    }
    out.update(fm.extra or {})
    return out


def _chunk_dict(c: Chunk) -> dict:
    return {"id": c.id, "bank": c.bank, "text": c.text, "prompt_pl": c.prompt_pl, "category": c.category}


def _session_or_404(db: Session, session_id: int) -> SpeakingSession:
    session = db.get(SpeakingSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej sesji")
    return session


def _pick_unused_pack(db: Session, domain_id: int) -> SourcePack | None:
    used_ids = {r[0] for r in db.query(SpeakingSession.source_pack_id).all()}
    return (
        db.query(SourcePack)
        .filter(SourcePack.domain_id == domain_id, SourcePack.status == "validated")
        .filter(~SourcePack.id.in_(used_ids) if used_ids else True)
        .order_by(SourcePack.created_at.asc())
        .first()
    )


def _pack_payload(db: Session, session: SpeakingSession, embed_unlocked: bool) -> dict:
    pack = db.get(SourcePack, session.source_pack_id)
    rounds = db.query(Round).filter(Round.session_id == session.id).order_by(Round.number).all()
    bank_a = chunk_scheduler.bank_a_chunks(db, pack.id)
    bank_b_ids = {
        row[0]
        for row in db.query(ChunkExposure.chunk_id)
        .filter(ChunkExposure.session_id == session.id)
        .distinct()
        .all()
    }
    bank_b = db.query(Chunk).filter(Chunk.id.in_(bank_b_ids)).all() if bank_b_ids else []
    return {
        "session_id": session.id,
        "domain": db.get(Domain, session.domain_id).name,
        "support_ceiling": session.support_ceiling_at_start,
        "writing_phase_active": session.support_ceiling_at_start >= WRITING_REHEARSAL_MIN_CEILING,
        "embed_mode_unlocked": embed_unlocked,
        "seed_text": pack.seed_text,
        "guiding_questions": pack.guiding_questions,
        "keywords": pack.keywords,
        "transfer_prompt": pack.transfer_prompt,
        "keyword_planning_seconds": KEYWORD_PLANNING_S[session.support_ceiling_at_start],
        "near_transfer_prompt": pack.transfer_prompt,
        "far_transfer_prompt": session.far_transfer_prompt,
        "transfer_order": session.transfer_order or ["near", "far"],
        "rounds": rounds and [
            {"number": r.number, "support_level": r.support_level, "prep_s": r.prep_s, "speak_limit_s": r.speak_limit_s}
            for r in rounds
        ],
        "bank_a_chunks": [_chunk_dict(c) for c in bank_a],
        "bank_b_chunks": [_chunk_dict(c) for c in bank_b],
        "interrupted_reason": session.interrupted_reason,
    }


@router.post("/start")
def start_session(background: BackgroundTasks, db: Session = Depends(get_db)):
    domain = domains_svc.get_active_domain(db)
    if domain is None:
        raise HTTPException(409, "Brak aktywnej domeny - dodaj ją w Ustawieniach")

    pack = _pick_unused_pack(db, domain.id)
    if pack is None:
        ceiling = support.get_current_ceiling(db)
        pack = pack_gen.generate_source_pack(db, domain, ceiling)
    if pack is None:
        raise HTTPException(503, "Nie udało się przygotować materiału - sprawdź klucz OpenAI w Ustawieniach")

    ceiling = support.get_current_ceiling(db)
    transfer_order = random.sample(["near", "far"], 2)
    far_prompt = transfer_probe_svc.generate_far_transfer_prompt(db)
    session = SpeakingSession(
        domain_id=domain.id,
        source_pack_id=pack.id,
        support_ceiling_at_start=ceiling,
        phases_completed=[],
        far_transfer_prompt=far_prompt,
        transfer_order=transfer_order,
    )
    db.add(session)
    db.flush()

    for r in _round_plan(ceiling):
        db.add(Round(session_id=session.id, **r))
    db.commit()

    session_number = db.query(SpeakingSession).filter(SpeakingSession.id <= session.id).count()
    embed_unlocked = session_number >= chunk_scheduler.EMBED_MODE_FROM_SESSION
    bank_b = chunk_scheduler.pick_bank_b_chunks(db, session_number)
    # zapisujemy dobór Banku B jako "przypisany do sesji" przez pustą ekspozycję
    # dostępową dopiero przy pierwszej próbie - tu tylko zwracamy listę do UI
    payload = _pack_payload(db, session, embed_unlocked)
    payload["bank_b_chunks"] = [_chunk_dict(c) for c in bank_b]

    if not llm_disabled_warning_needed(db):
        background.add_task(_maybe_pregenerate_next_pack, domain.id, ceiling)

    return payload


def llm_disabled_warning_needed(db: Session) -> bool:
    from ..services import llm

    return not llm.llm_enabled()


@router.get("/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    session_number = db.query(SpeakingSession).filter(SpeakingSession.id <= session.id).count()
    embed_unlocked = session_number >= chunk_scheduler.EMBED_MODE_FROM_SESSION
    return _pack_payload(db, session, embed_unlocked)


@router.get("/{session_id}/status")
def session_status(session_id: int, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    return {"interrupted": session.interrupted_reason is not None, "interrupted_reason": session.interrupted_reason}


@router.post("/{session_id}/writing-rehearsal")
def submit_writing_rehearsal(session_id: int, body: dict, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    if session.support_ceiling_at_start < WRITING_REHEARSAL_MIN_CEILING:
        raise HTTPException(422, "Faza -1 nieaktywna przy tym poziomie wsparcia")
    text = str(body.get("text", "")).strip()
    duration_s = float(body.get("duration_s", 0))
    if not text:
        raise HTTPException(422, "Brak tekstu")
    wr = WritingRehearsal(session_id=session_id, text=text, duration_s=duration_s, word_count=len(text.split()))
    db.add(wr)
    db.commit()
    return {"ok": True, "word_count": wr.word_count}


@router.post("/{session_id}/keyword-plan")
def submit_keyword_plan(session_id: int, body: dict, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    items = body.get("items", [])
    if not isinstance(items, list) or not items:
        raise HTTPException(422, "Brak haseł")
    if len(items) > KEYWORD_PLAN_MAX_ITEMS:
        raise HTTPException(422, f"Maksymalnie {KEYWORD_PLAN_MAX_ITEMS} hasła")
    cleaned = [str(item).strip() for item in items]
    if any(not item for item in cleaned):
        raise HTTPException(422, "Puste hasło")
    if any(len(item.split()) > KEYWORD_PLAN_MAX_WORDS for item in cleaned):
        raise HTTPException(422, f"Maksymalnie {KEYWORD_PLAN_MAX_WORDS} słów na hasło")

    plan = KeywordPlan(
        session_id=session_id,
        items=cleaned,
        planning_seconds=KEYWORD_PLANNING_S[session.support_ceiling_at_start],
    )
    db.add(plan)
    db.commit()
    return {"ok": True, "items": cleaned}


def _save_upload(session_id: int, subdir: str, attempt_id: int, data: bytes) -> str:
    audio_dir = get_settings().audio_dir / str(session_id) / subdir
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{attempt_id}.wav"
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def _process_round_attempt(attempt_id: int, session_id: int, round_number: int) -> None:
    attempt_pipeline.process_attempt(attempt_id)
    if round_number != 3:
        return
    db = db_session()
    try:
        session = db.get(SpeakingSession, session_id)
        if session and session.interrupted_reason is None and support.should_interrupt_session(db, session_id):
            session.interrupted_reason = "low_phonation_r3"
            db.commit()
    finally:
        db.close()


@router.post("/{session_id}/rounds/{round_number}/attempts", status_code=202)
async def create_round_attempt(
    session_id: int,
    round_number: int,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    _session_or_404(db, session_id)
    round_ = (
        db.query(Round)
        .filter(Round.session_id == session_id, Round.number == round_number)
        .first()
    )
    if round_ is None:
        raise HTTPException(404, "Nie ma takiej rundy")
    try:
        meta = json.loads(payload)
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    attempt = Attempt(round_id=round_.id, t0_iso=now_iso(), t0_offset_samples=t0_offset_samples, status="processing")
    db.add(attempt)
    db.commit()
    attempt.audio_path = _save_upload(session_id, f"round_{round_number}", attempt.id, await audio.read())
    db.commit()

    background.add_task(_process_round_attempt, attempt.id, session_id, round_number)
    return {"attempt_id": attempt.id}


def _process_transfer_probe(attempt_id: int, probe_id: int, question: str) -> None:
    attempt_pipeline.process_attempt(attempt_id)
    db = db_session()
    try:
        attempt = db.get(Attempt, attempt_id)
        probe = db.get(TransferProbe, probe_id)
        if attempt is None or probe is None or attempt.status != "done":
            return
        fm = db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == attempt.id).first()
        outcome = transfer_probe_svc.classify_outcome(
            question, attempt.transcript, fm.phonation_time_ratio if fm else None
        )
        probe.outcome = outcome
        probe.outcome_classified_at = now_iso()
        db.commit()
        support.update_baseline_from_transfer_probe(db, probe)
    finally:
        db.close()


@router.post("/{session_id}/transfer-probe/{probe_type}", status_code=202)
async def create_transfer_probe(
    session_id: int,
    probe_type: str,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    if probe_type not in ("near", "far"):
        raise HTTPException(422, "probe_type musi być 'near' albo 'far'")
    session = _session_or_404(db, session_id)
    pack = db.get(SourcePack, session.source_pack_id)
    prompt = pack.transfer_prompt if probe_type == "near" else session.far_transfer_prompt
    if not prompt:
        raise HTTPException(409, "Pytanie dla tej sondy nie jest dostępne")
    try:
        meta = json.loads(payload)
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    order = (session.transfer_order or ["near", "far"]).index(probe_type) + 1
    existing = (
        db.query(TransferProbe)
        .filter(TransferProbe.session_id == session_id, TransferProbe.probe_type == probe_type)
        .first()
    )
    probe = existing or TransferProbe(
        session_id=session_id, probe_type=probe_type, prompt=prompt, order_in_session=order
    )
    db.add(probe)
    db.commit()

    attempt = Attempt(
        transfer_probe_id=probe.id, t0_iso=now_iso(), t0_offset_samples=t0_offset_samples, status="processing"
    )
    db.add(attempt)
    db.commit()
    attempt.audio_path = _save_upload(session_id, f"transfer_{probe_type}", attempt.id, await audio.read())
    probe.attempt_id = attempt.id
    db.commit()

    background.add_task(_process_transfer_probe, attempt.id, probe.id, prompt)
    return {"attempt_id": attempt.id, "probe_id": probe.id}


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, db: Session = Depends(get_db)):
    attempt = db.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "Nie ma takiej próby")
    fm = None
    if attempt.status == "done":
        fm = db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == attempt.id).first()
    return {
        "attempt_id": attempt.id,
        "status": attempt.status,
        "transcript": attempt.transcript if attempt.status == "done" else None,
        "metrics": _fm_dict(fm),
    }


@router.post("/{session_id}/chunks/{chunk_id}/access")
def chunk_access_exposure(session_id: int, chunk_id: int, body: dict, db: Session = Depends(get_db)):
    _session_or_404(db, session_id)
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "Nie ma takiego chunku")
    rt_ms = float(body.get("rt_ms", 0))
    ce = ChunkExposure(
        chunk_id=chunk_id, session_id=session_id, mode="access", rt_ms=rt_ms,
        success=rt_ms < chunk_scheduler.FAST_RT_MS,
    )
    db.add(ce)
    db.commit()
    return {"ok": True}


@router.post("/{session_id}/chunks/{chunk_id}/embed", status_code=202)
async def chunk_embed_exposure(
    session_id: int,
    chunk_id: int,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    _session_or_404(db, session_id)
    chunk = db.get(Chunk, chunk_id)
    if chunk is None:
        raise HTTPException(404, "Nie ma takiego chunku")
    try:
        meta = json.loads(payload)
        t0_offset_samples = int(meta.get("t0_offset_samples", 0))
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    ce = ChunkExposure(chunk_id=chunk_id, session_id=session_id, mode="embed")
    db.add(ce)
    db.commit()
    attempt = Attempt(chunk_exposure_id=ce.id, t0_iso=now_iso(), t0_offset_samples=t0_offset_samples, status="processing")
    db.add(attempt)
    db.commit()
    attempt.audio_path = _save_upload(session_id, "chunk_embed", attempt.id, await audio.read())
    db.commit()

    background.add_task(chunk_scheduler.process_embed_attempt, attempt.id, ce.id)
    return {"attempt_id": attempt.id}


@router.post("/{session_id}/self-transcription")
def submit_self_transcription(session_id: int, body: dict, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    round1 = db.query(Round).filter(Round.session_id == session_id, Round.number == 1).first()
    if round1 is None:
        raise HTTPException(404, "Nie ma R1 dla tej sesji")
    r1_attempt = (
        db.query(Attempt)
        .filter(Attempt.round_id == round1.id, Attempt.status == "done")
        .order_by(Attempt.id.desc())
        .first()
    )
    if r1_attempt is None:
        raise HTTPException(404, "R1 jeszcze nie przetworzone")
    if db.query(SelfTranscription).filter(SelfTranscription.attempt_id == r1_attempt.id).first():
        raise HTTPException(409, "Zadanie już wykonane dla tej sesji")

    user_text = str(body.get("user_text", "")).strip()
    if not user_text:
        raise HTTPException(422, "Brak transkrypcji")

    st = SelfTranscription(
        attempt_id=r1_attempt.id, user_text=user_text, whisper_text=r1_attempt.transcript or ""
    )
    db.add(st)
    # zadanie wykonane - audio R1 nie musi już czekać do wygaśnięcia
    if r1_attempt.audio_path:
        from pathlib import Path

        try:
            Path(r1_attempt.audio_path).unlink(missing_ok=True)
        except OSError:
            pass
        r1_attempt.audio_path = None
        r1_attempt.audio_expires_at = None
    db.commit()
    return {"user_text": st.user_text, "whisper_text": st.whisper_text}


@router.get("/{session_id}/self-transcription/available")
def self_transcription_available(session_id: int, db: Session = Depends(get_db)):
    round1 = db.query(Round).filter(Round.session_id == session_id, Round.number == 1).first()
    if round1 is None:
        return {"available": False}
    r1_attempt = (
        db.query(Attempt)
        .filter(Attempt.round_id == round1.id, Attempt.status == "done")
        .order_by(Attempt.id.desc())
        .first()
    )
    if r1_attempt is None or not r1_attempt.audio_path:
        return {"available": False}
    already_done = bool(
        db.query(SelfTranscription).filter(SelfTranscription.attempt_id == r1_attempt.id).first()
    )
    return {"available": not already_done}


def _outcome_note(outcome: str | None) -> str | None:
    if outcome in ("answered", "redirected"):
        return "You kept speaking through the transfer question."
    if outcome == "stalled":
        return "The transfer question stalled you this time - that happens, it's meant to be hard."
    return None


def _probe_summary(db: Session, session_id: int, probe_type: str) -> dict:
    probe = (
        db.query(TransferProbe)
        .filter(TransferProbe.session_id == session_id, TransferProbe.probe_type == probe_type)
        .first()
    )
    fm = (
        db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == probe.attempt_id).first()
        if probe and probe.attempt_id
        else None
    )
    deltas = {
        key: {
            "value": getattr(fm, key) if fm else None,
            "baseline": support.get_baseline_median(db, key, probe_type),
        }
        for key in support.BASELINE_METRICS
    }
    return {
        "outcome_note": _outcome_note(probe.outcome if probe else None),
        "deltas": deltas,
    }


def _maybe_pregenerate_next_pack(domain_id: int, ceiling: int) -> None:
    db = db_session()
    try:
        domain = db.get(Domain, domain_id)
        if domain is None or domain.status != "active":
            return
        if _pick_unused_pack(db, domain_id) is not None:
            return
        pack_gen.generate_source_pack(db, domain, ceiling)
    finally:
        db.close()


@router.post("/{session_id}/end")
def end_session(session_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    session = _session_or_404(db, session_id)
    if session.ended_at is not None:
        raise HTTPException(409, "Sesja już zakończona")

    session.ended_at = now_iso()
    domain = db.get(Domain, session.domain_id)
    domains_svc.advance_domain_after_session(db, domain)
    db.commit()

    event = support.evaluate_and_apply(db, session)

    session_number = db.query(SpeakingSession).filter(SpeakingSession.id <= session.id).count()
    chunk_ids = {
        row[0]
        for row in db.query(ChunkExposure.chunk_id)
        .filter(ChunkExposure.session_id == session_id, ChunkExposure.mode == "access")
        .join(Chunk, Chunk.id == ChunkExposure.chunk_id)
        .filter(Chunk.bank == "function")
        .distinct()
        .all()
    }
    for cid in chunk_ids:
        chunk = db.get(Chunk, cid)
        if chunk:
            chunk_scheduler.update_schedule_after_session(db, chunk, session_number)
    db.commit()

    active_domain = domains_svc.get_active_domain(db)
    if active_domain is not None:
        background.add_task(_maybe_pregenerate_next_pack, active_domain.id, support.get_current_ceiling(db))

    return {
        "session_id": session.id,
        "ended_reason": session.interrupted_reason or "completed",
        "support_ceiling": support.get_current_ceiling(db),
        "support_changed": event.direction if event else None,
        "near": _probe_summary(db, session_id, "near"),
        "far": _probe_summary(db, session_id, "far"),
    }
