"""Grammar: krótkie mówione rundy z oceną po każdej odpowiedzi.

Trzy części:
- bank zadań (grammar_items): startowy zestaw z repo + dogenerowywanie w tle,
  dzięki czemu runda składa się natychmiast, bez czekania na LLM;
- plan rundy: powtórki po przerwie, umiejętności w nauce, ćwiczone samodzielnie
  i sondy nowych - zawsze wymieszane, żeby formę wybierało znaczenie;
- ocena: po transkrypcji jedno krótkie żądanie LLM na odpowiedź, wynik od razu
  zmienia poziom umiejętności (reguły w services/skills.py).

Moduł jest poza statystykami płynności: ocenia poprawność struktury.
"""

import json
import logging
import random
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import db_session
from ..models import (
    GrammarAnswer,
    GrammarBankItem,
    GrammarRound,
    GrammarSkill,
    PersonalContext,
    ShadowAttempt,
    now_iso,
)
from . import llm, skills, transcription, vad

logger = logging.getLogger(__name__)

ROUND_SIZE = 8
MAX_REVIEWS = 3
MAX_LEARNING_SKILLS = 2  # tyle umiejętności "w nauce" naraz w jednej rundzie
LEARNING_BACKLOG_LIMIT = 3  # przy tylu w nauce nie sondujemy nowych
MAX_PROBES = 6
MAX_EXTRAS = 2  # powroty błędnych zadań w tej samej rundzie
WEEKLY_GOAL_DAYS = 5

# ile zadań każdego formatu w jednej porcji generowania dla umiejętności
GEN_COUNTS = {"guided": 3, "situation": 6, "translate": 4, "fix": 2, "personal": 2}
MIN_UNSEEN = 4  # poniżej tylu nieużytych zadań umiejętność dostaje nową porcję
MAX_ITEMS_PER_SKILL = 90
TOP_UP_SKILLS_PER_RUN = 3
UPCOMING_NEW = 6  # dla tylu kolejnych nowych umiejętności trzymamy zapas

GENERATE_TIMEOUT_S = 180
GRADE_TIMEOUT_S = 30

FORMATS = ("guided", "situation", "translate", "fix", "personal", "own")
UNAIDED_FORMATS = ("own", "situation", "translate", "fix", "personal")

DEFAULT_CONTEXT = (
    "An experienced professional working at the intersection of marketing, product "
    "and technology; everyday adult life in a city."
)

_top_up_lock = threading.Lock()


def local_today() -> date:
    return date.today()


def _local_date(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone().date()


# --- bank zadań ---------------------------------------------------------------


def load_seed(db: Session) -> int:
    """Wczytuje startowy bank z repo, jeśli tabela jest pusta."""
    if db.query(GrammarBankItem).count() > 0:
        return 0
    path = get_settings().grammar_seed_items_path
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Nie udało się wczytać startowego banku zadań (%s)", path)
        return 0
    added = 0
    for it in raw.get("items", []):
        if skills.skill_def(it.get("skill_id", "")) is None or it.get("fmt") not in FORMATS:
            continue
        db.add(
            GrammarBankItem(
                skill_id=it["skill_id"], fmt=it["fmt"], prompt=it["prompt"],
                cue=it.get("cue", ""), hint=it.get("hint", ""),
                model_answer=it["model_answer"],
                accepted_variants=it.get("accepted_variants", []), source="seed",
            )
        )
        added += 1
    db.commit()
    return added


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def valid_generated(item: llm.GeneratedBankItem) -> bool:
    """Odsiewa zadania, które zdradzają odpowiedź albo są puste."""
    if item.fmt not in GEN_COUNTS:
        return False
    if not item.prompt.strip() or not item.model_answer.strip():
        return False
    answer = _words(item.model_answer)
    if item.fmt == "guided":
        cue = _words(item.cue)
        # początek zdania to najwyżej kilka słów i wyraźnie mniej niż cała odpowiedź
        if not cue or len(cue) > 4 or len(cue) * 2 >= max(len(answer), 1):
            return False
    if item.fmt in ("guided", "situation", "personal"):
        # gotowa odpowiedź nie może stać w poleceniu
        if len(answer) >= 4 and " ".join(answer) in " ".join(_words(item.prompt)):
            return False
    return True


def _context(db: Session) -> str:
    ctx = (
        db.query(PersonalContext)
        .filter(PersonalContext.active.is_(True))
        .order_by(PersonalContext.version.desc())
        .first()
    )
    return ctx.content.strip() if ctx and ctx.content.strip() else DEFAULT_CONTEXT


def request_items(sdef: dict, context: str, existing_answers: list[str]) -> list[llm.GeneratedBankItem]:
    """Jedno żądanie LLM = porcja zadań dla jednej umiejętności (już odsiana).

    Bez bazy, żeby ten sam kod budował też startowy bank (scripts/build_seed_bank.py).
    """
    result = llm.complete_json(
        "generate_grammar_items",
        {
            "meaning": sdef["meaning"],
            "pattern": sdef["pattern"],
            "example": sdef["example"],
            "name": sdef.get("name", ""),
            "trap": sdef.get("trap_pl", "") or "(none)",
            "context": context,
            "existing": (
                json.dumps(existing_answers, ensure_ascii=False) if existing_answers else "(none yet)"
            ),
            **{f"n_{k}": str(v) for k, v in GEN_COUNTS.items()},
        },
        llm.GeneratedBankItems,
        model=get_settings().openai_grammar_model or None,
        timeout=GENERATE_TIMEOUT_S,
        temperature=0.9,
    )
    if result is None:
        return []
    out = []
    for it in result.items:
        if not valid_generated(it):
            continue
        it.prompt = it.prompt.strip()
        it.cue = it.cue.strip() if it.fmt == "guided" else ""
        it.hint = it.hint.strip() if it.fmt == "situation" else ""
        it.model_answer = it.model_answer.strip()
        it.accepted_variants = [v.strip() for v in it.accepted_variants if v.strip()][:3]
        out.append(it)
    return out


def generate_items(db: Session, skill_id: str) -> int:
    """Dokłada do banku porcję zadań dla jednej umiejętności. Zwraca ile dodano."""
    sdef = skills.skill_def(skill_id)
    if sdef is None:
        return 0
    existing = db.query(GrammarBankItem).filter(GrammarBankItem.skill_id == skill_id).all()
    known = {(e.fmt, e.prompt.strip().lower()) for e in existing}
    added = 0
    for it in request_items(sdef, _context(db), [e.model_answer for e in existing[-25:]]):
        key = (it.fmt, it.prompt.lower())
        if key in known:
            continue
        known.add(key)
        db.add(
            GrammarBankItem(
                skill_id=skill_id, fmt=it.fmt, prompt=it.prompt, cue=it.cue, hint=it.hint,
                model_answer=it.model_answer, accepted_variants=it.accepted_variants,
                source="generated",
            )
        )
        added += 1
    db.commit()
    return added


def _skills_needing_items(db: Session) -> list[str]:
    """Umiejętności, które niedługo pojawią się w rundach, a mają mało świeżych zadań."""
    rows = skills.ensure_rows(db)
    order = [s["id"] for s in skills.all_skills()]
    active = [sid for sid in order if rows[sid].level in (skills.LEARNING, skills.UNAIDED)]
    upcoming = [sid for sid in order if rows[sid].level == skills.NEW][:UPCOMING_NEW]
    settled = [sid for sid in order if rows[sid].level >= skills.SOLID]
    out = []
    for sid in active + upcoming + settled:
        items = db.query(GrammarBankItem).filter(GrammarBankItem.skill_id == sid).all()
        unseen = sum(1 for i in items if i.times_shown == 0)
        if unseen < MIN_UNSEEN and len(items) < MAX_ITEMS_PER_SKILL:
            out.append(sid)
    return out


def top_up() -> int:
    """Dogenerowuje zadania w tle. Bezpieczne do wołania wielokrotnie: jedna
    kopia naraz, kolejne wywołania wracają od razu."""
    if not llm.llm_enabled() or not _top_up_lock.acquire(blocking=False):
        return 0
    db = db_session()
    try:
        done = 0
        for sid in _skills_needing_items(db)[:TOP_UP_SKILLS_PER_RUN]:
            if generate_items(db, sid) > 0:
                done += 1
        return done
    except Exception:
        logger.exception("Uzupełnianie banku zadań nie powiodło się")
        return 0
    finally:
        db.close()
        _top_up_lock.release()


# --- plan rundy ---------------------------------------------------------------


def _pick_item(
    db: Session, skill_id: str, fmts: tuple[str, ...], used: set[int], fmt_counts: dict[str, int]
) -> GrammarBankItem | None:
    items = [
        i
        for i in db.query(GrammarBankItem).filter(GrammarBankItem.skill_id == skill_id).all()
        if i.fmt in fmts and i.id not in used
    ]
    if not items:
        return None
    # najpierw nieużyte, potem format, którego w tej rundzie jeszcze mało
    items.sort(key=lambda i: (i.times_shown, fmt_counts.get(i.fmt, 0), random.random()))
    return items[0]


def _fmts_for(kind: str, skill: GrammarSkill, ahead: int = 0) -> list[tuple[str, ...]]:
    """Dozwolone formaty w kolejności preferencji (kolejne krotki to plan B).

    ahead = ile zadań tej umiejętności jest już wcześniej w tej samej rundzie.
    Plan powstaje z góry, więc zakładamy, że tamte pójdą dobrze: po dwóch
    zadaniach z widocznym kształtem trzecie jest już samą sytuacją.
    """
    if kind == "probe":
        return [("situation",), ("translate",)]
    if kind in ("learn", "extra") and skill.level <= skills.LEARNING:
        if skill.streak + ahead < skills.GUIDED_STREAK:
            return [("guided",), ("situation",), ("translate",)]
        return [("situation", "translate"), ("guided",)]
    return [UNAIDED_FORMATS]


def _add_entry(
    db: Session,
    entries: list[dict],
    used: set[int],
    fmt_counts: dict[str, int],
    skill: GrammarSkill,
    kind: str,
) -> bool:
    ahead = sum(1 for e in entries if e["skill_id"] == skill.skill_id)
    for fmts in _fmts_for(kind, skill, ahead):
        item = _pick_item(db, skill.skill_id, fmts, used, fmt_counts)
        if item is not None:
            used.add(item.id)
            fmt_counts[item.fmt] = fmt_counts.get(item.fmt, 0) + 1
            entries.append(
                {"item_id": item.id, "skill_id": skill.skill_id, "kind": kind, "fmt": item.fmt}
            )
            return True
    return False


def plan_round(db: Session, today: date) -> list[dict]:
    rows = skills.ensure_rows(db)
    ordered = [rows[s["id"]] for s in skills.all_skills()]
    used: set[int] = set()
    fmt_counts: dict[str, int] = {}

    reviews: list[dict] = []
    due = sorted((s for s in ordered if skills.is_due(s, today)), key=lambda s: s.next_due or "")
    for s in due[:MAX_REVIEWS]:
        _add_entry(db, reviews, used, fmt_counts, s, "review")

    rest: list[dict] = []
    learning = [s for s in ordered if s.level == skills.LEARNING]
    # te, nad którymi praca już trwa, mają pierwszeństwo - kończymy zaczęte
    learning.sort(key=lambda s: s.last_seen or "", reverse=True)
    for s in learning[:MAX_LEARNING_SKILLS]:
        for _ in range(2):
            _add_entry(db, rest, used, fmt_counts, s, "learn")

    unaided = sorted(
        (s for s in ordered if s.level == skills.UNAIDED), key=lambda s: s.last_seen or ""
    )
    new = [s for s in ordered if s.level == skills.NEW]

    def remaining() -> int:
        return ROUND_SIZE - len(reviews) - len(rest)

    probe_quota = 0
    if new and len(learning) < LEARNING_BACKLOG_LIMIT:
        probe_quota = min(len(new), MAX_PROBES, remaining(), max(2, remaining() - len(unaided)))

    for s in unaided[: max(0, remaining() - probe_quota)]:
        _add_entry(db, rest, used, fmt_counts, s, "practice")

    added = 0
    for s in new:
        if added >= probe_quota or remaining() <= 0:
            break
        if _add_entry(db, rest, used, fmt_counts, s, "probe"):
            added += 1

    # dopełnienie: drugie zadania z ćwiczonych, potem utrwalone, potem reszta nauki
    solid = sorted(
        (s for s in ordered if s.level >= skills.SOLID and not skills.is_due(s, today)),
        key=lambda s: s.last_seen or "",
    )
    # w nauce najpierw te, które w tej rundzie jeszcze nic nie dostały
    waiting = learning[MAX_LEARNING_SKILLS:] + learning[:MAX_LEARNING_SKILLS]
    for pool, kind in ((unaided, "practice"), (solid, "practice"), (waiting, "learn")):
        for s in pool:
            if remaining() <= 0:
                break
            _add_entry(db, rest, used, fmt_counts, s, kind)

    random.shuffle(rest)
    entries = reviews + rest
    for index, e in enumerate(entries):
        e["index"] = index
    return entries


def create_round(db: Session, today: date | None = None) -> GrammarRound | None:
    load_seed(db)
    entries = plan_round(db, today or local_today())
    if not entries:
        return None
    stamp = now_iso()
    for e in entries:
        item = db.get(GrammarBankItem, e["item_id"])
        item.times_shown += 1
        item.last_shown = stamp
    rnd = GrammarRound(plan=entries)
    db.add(rnd)
    db.commit()
    return rnd


def add_extra(db: Session, rnd: GrammarRound, skill_id: str) -> dict | None:
    """Błędne zadanie wraca w tej samej rundzie jako inna sytuacja tej samej umiejętności."""
    plan = list(rnd.plan)
    if sum(1 for e in plan if e["kind"] == "extra") >= MAX_EXTRAS:
        return None
    skill = db.get(GrammarSkill, skill_id)
    if skill is None:
        return None
    used = {e["item_id"] for e in plan}
    fmt_counts: dict[str, int] = {}
    added: list[dict] = []
    if not _add_entry(db, added, used, fmt_counts, skill, "extra"):
        return None
    entry = added[0]
    entry["index"] = len(plan)
    item = db.get(GrammarBankItem, entry["item_id"])
    item.times_shown += 1
    item.last_shown = now_iso()
    rnd.plan = plan + [entry]  # nowa lista: SQLAlchemy nie śledzi zmian w miejscu
    db.commit()
    return entry


def entry_payload(db: Session, entry: dict) -> dict:
    item = db.get(GrammarBankItem, entry["item_id"])
    sdef = skills.skill_def(entry["skill_id"]) or {}
    guided = entry["fmt"] == "guided"
    return {
        "index": entry["index"],
        "kind": entry["kind"],
        "fmt": entry["fmt"],
        "skill_id": entry["skill_id"],
        "prompt": item.prompt,
        "cue": item.cue if guided else "",
        # podpowiedź o znaczeniu tylko na etapie nauki; dalej nie ma kółek treningowych
        "hint": item.hint if entry["kind"] in ("learn", "extra") and not guided else "",
        "show_pattern": guided,
        "pattern": sdef.get("pattern", ""),
        "meaning": sdef.get("meaning", ""),
        "name": sdef.get("name", ""),
        "model_answer": item.model_answer,
        "accepted_variants": item.accepted_variants or [],
    }


def round_payload(db: Session, rnd: GrammarRound) -> dict:
    return {
        "round_id": rnd.id,
        "entries": [entry_payload(db, e) for e in rnd.plan],
        "summary": rnd.summary,
    }


# --- ocena ----------------------------------------------------------------------


def _apply(db: Session, answer: GrammarAnswer, item: GrammarBankItem | None) -> None:
    skill = db.get(GrammarSkill, answer.skill_id)
    if skill is None or answer.verdict is None:
        return
    fast = (
        answer.latency_ms is not None
        and item is not None
        and answer.latency_ms <= skills.fast_threshold_ms(item.prompt, item.cue)
    )
    before, after = skills.apply_answer(
        skill, answer.verdict, hint_used=answer.hint_used, fast=fast, today=local_today()
    )
    answer.level_before, answer.level_after = before, after


def grade(db: Session, answer: GrammarAnswer) -> None:
    """Ocena jednej odpowiedzi na podstawie transkryptu. Zawsze kończy werdyktem."""
    item = db.get(GrammarBankItem, answer.item_id)
    sdef = skills.skill_def(answer.skill_id) or {}
    transcript = (answer.transcript or "").strip()
    if not transcript or item is None:
        answer.verdict = "unclear"
        return
    graded = llm.complete_json(
        "grade_grammar_answer",
        {
            "meaning": sdef.get("meaning", ""),
            "pattern": sdef.get("pattern", ""),
            "trap": sdef.get("trap_pl", "") or "(none)",
            "fmt": answer.fmt,
            "prompt": item.prompt,
            "cue": item.cue or "(none)",
            "model_answer": item.model_answer,
            "accepted_variants": json.dumps(item.accepted_variants or [], ensure_ascii=False),
            "transcript": transcript,
        },
        llm.GradedAnswer,
        model=get_settings().openai_grade_model or None,
        timeout=GRADE_TIMEOUT_S,
        temperature=0.0,
    )
    if graded is None:
        answer.verdict = "unclear"
        answer.explanation = "This one could not be checked."
        return
    verdict = graded.verdict.strip().lower()
    answer.verdict = verdict if verdict in (*skills.GRADED, "unclear") else "unclear"
    wrong = answer.verdict in ("incorrect", "avoided")
    answer.error_type = (graded.error_type.strip().lower() or None) if wrong else None
    answer.explanation = (graded.explanation.strip() or None) if wrong else None
    answer.note_pl = (graded.note_pl.strip() or None) if wrong else None
    answer.corrected = (graded.corrected.strip() or item.model_answer) if wrong else None
    answer.reaction = (graded.reaction.strip() or None) if answer.verdict == "correct" else None


def process_answer(answer_id: int, audio_path: str) -> None:
    """Zadanie w tle: czas reakcji z VAD, transkrypcja, ocena, zmiana poziomu."""
    db = db_session()
    path = Path(audio_path)
    try:
        answer = db.get(GrammarAnswer, answer_id)
        if answer is None:
            return
        audio = vad.read_wav_mono16k(path)
        segments = vad.get_vad().speech_segments(audio)
        # nagrywanie startuje razem z poleceniem, więc początek mowy = czas reakcji
        answer.latency_ms = round(segments[0][0] * 1000) if segments else None

        text = ""
        if segments:
            text = transcription.transcribe_text(path) or ""
        answer.transcript = text or None

        grade(db, answer)
        _apply(db, answer, db.get(GrammarBankItem, answer.item_id))
        answer.status = "done"
        db.commit()
    except Exception:
        logger.exception("Analiza odpowiedzi grammar %s nie powiodła się", answer_id)
        db.rollback()
        answer = db.get(GrammarAnswer, answer_id)
        if answer:
            answer.status = "error"
            db.commit()
    finally:
        db.close()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Nie udało się usunąć pliku tymczasowego %s", path)


def record_skip(db: Session, rnd: GrammarRound, entry: dict) -> GrammarAnswer:
    """"Nie wiem" - bez nagrania i bez LLM: liczy się jak błąd, pokazujemy wzorzec."""
    item = db.get(GrammarBankItem, entry["item_id"])
    answer = GrammarAnswer(
        round_id=rnd.id, entry_index=entry["index"], item_id=entry["item_id"],
        skill_id=entry["skill_id"], kind=entry["kind"], fmt=entry["fmt"],
        skipped=True, hint_used=False, status="done", verdict="incorrect",
        corrected=item.model_answer if item else None,
    )
    db.add(answer)
    _apply(db, answer, item)
    db.commit()
    return answer


def answer_payload(answer: GrammarAnswer) -> dict:
    sdef = skills.skill_def(answer.skill_id) or {}
    return {
        "answer_id": answer.id,
        "status": answer.status,
        "transcript": answer.transcript,
        "latency_ms": answer.latency_ms,
        "verdict": answer.verdict,
        "error_type": answer.error_type,
        "explanation": answer.explanation,
        "note_pl": answer.note_pl or (sdef.get("trap_pl") or None if answer.skipped else None),
        "corrected": answer.corrected,
        "reaction": answer.reaction,
        "skill_id": answer.skill_id,
        "skill_label": sdef.get("meaning", answer.skill_id),
        "level_before": answer.level_before,
        "level_after": answer.level_after,
    }


def _latest_answers(db: Session, round_id: int) -> list[GrammarAnswer]:
    rows = (
        db.query(GrammarAnswer)
        .filter(GrammarAnswer.round_id == round_id)
        .order_by(GrammarAnswer.id)
        .all()
    )
    return list({r.entry_index: r for r in rows}.values())


def finish_round(db: Session, rnd: GrammarRound) -> dict:
    answers = _latest_answers(db, rnd.id)
    graded = [a for a in answers if a.verdict in skills.GRADED]
    changes: dict[str, dict] = {}
    for a in sorted(answers, key=lambda a: a.id):
        if a.level_before is None or a.level_after is None:
            continue
        c = changes.setdefault(a.skill_id, {"from": a.level_before, "to": a.level_after})
        c["to"] = a.level_after
    moved = []
    for sid, c in changes.items():
        if c["from"] == c["to"]:
            continue
        sdef = skills.skill_def(sid) or {}
        moved.append(
            {
                "skill_id": sid,
                "label": sdef.get("meaning", sid),
                "from": c["from"],
                "to": c["to"],
                # sonda nowej umiejętności, która wypadła źle, to nie degradacja
                "up": c["to"] > c["from"] and not (c["from"] == skills.NEW and c["to"] == skills.LEARNING),
            }
        )
    missed = []
    for a in answers:
        if a.verdict in ("incorrect", "avoided") and a.skill_id not in missed:
            missed.append(a.skill_id)
    latencies = sorted(a.latency_ms for a in graded if a.latency_ms is not None and a.verdict == "correct")
    summary = {
        "answered": len(answers),
        "graded": len(graded),
        "correct": sum(1 for a in graded if a.verdict == "correct"),
        "moved": moved,
        "to_revisit": [
            {"skill_id": sid, "label": (skills.skill_def(sid) or {}).get("meaning", sid)} for sid in missed
        ],
        "median_latency_ms": latencies[len(latencies) // 2] if latencies else None,
    }
    rnd.summary = summary
    rnd.ended_at = now_iso()
    db.commit()
    return summary


# --- ekran startowy i mapa -------------------------------------------------------


def _practice_dates(db: Session) -> set[date]:
    stamps = [a.created_at for a in db.query(GrammarAnswer.created_at).all()]
    stamps += [a.created_at for a in db.query(ShadowAttempt.created_at).all()]
    return {_local_date(s) for s in stamps if s}


def home(db: Session, today: date | None = None) -> dict:
    today = today or local_today()
    load_seed(db)
    rows = skills.ensure_rows(db)
    defs = skills.all_skills()
    counts = {name: 0 for name in skills.LEVEL_NAMES.values()}
    for s in defs:
        counts[skills.LEVEL_NAMES[rows[s["id"]].level]] += 1

    learning = [s for s in defs if rows[s["id"]].level == skills.LEARNING]
    learning.sort(key=lambda s: rows[s["id"]].last_seen or "", reverse=True)
    next_new = next((s for s in defs if rows[s["id"]].level == skills.NEW), None)

    days = _practice_dates(db)
    monday = today - timedelta(days=today.weekday())
    week = [
        {"date": (monday + timedelta(days=i)).isoformat(), "done": (monday + timedelta(days=i)) in days}
        for i in range(7)
    ]
    answers_today = sum(
        1 for a in db.query(GrammarAnswer.created_at).all() if _local_date(a.created_at) == today
    )
    return {
        "llm_ready": llm.llm_enabled(),
        "bank_items": db.query(GrammarBankItem).count(),
        "total_skills": len(defs),
        "counts": counts,
        "due_today": sum(1 for s in rows.values() if skills.is_due(s, today)),
        "in_progress": [s["meaning"] for s in learning[:MAX_LEARNING_SKILLS]],
        "next_new": next_new["meaning"] if next_new else None,
        "week": week,
        "week_days_done": sum(1 for d in week if d["done"]),
        "weekly_goal": WEEKLY_GOAL_DAYS,
        "today_index": today.weekday(),
        "answers_today": answers_today,
        "answers_total": db.query(GrammarAnswer).count(),
    }


def map_payload(db: Session, today: date | None = None) -> dict:
    today = today or local_today()
    rows = skills.ensure_rows(db)
    out = []
    for g in skills.groups():
        members = []
        for s in skills.all_skills():
            if s["group"] != g["id"]:
                continue
            r = rows[s["id"]]
            members.append(
                {
                    "id": s["id"],
                    "meaning": s["meaning"],
                    "pl": s.get("pl", ""),
                    "pattern": s["pattern"],
                    "example": s["example"],
                    "name": s.get("name", ""),
                    "trap_pl": s.get("trap_pl", ""),
                    "level": r.level,
                    "level_name": skills.LEVEL_NAMES[r.level],
                    "due": skills.is_due(r, today),
                    "next_due": r.next_due,
                    "attempts": r.attempts,
                    "correct": r.correct,
                    "wild_uses": r.wild_uses,
                }
            )
        out.append({"id": g["id"], "label": g["label"], "skills": members})
    return {"groups": out}


# --- most do rozmów w subskrypcji ------------------------------------------------


def talk_prompt(db: Session) -> dict:
    """Gotowy tekst do wklejenia w rozmowie głosowej poza aplikacją."""
    rows = skills.ensure_rows(db)
    defs = skills.all_skills()
    active = [s for s in defs if rows[s["id"]].level in (skills.LEARNING, skills.UNAIDED)]
    active.sort(key=lambda s: rows[s["id"]].last_seen or "", reverse=True)
    chosen = active[:3] or [s for s in defs if rows[s["id"]].level == skills.NEW][:3] or defs[:3]
    lines = "\n".join(f"- {s['meaning']} (for example: \"{s['example']}\")" for s in chosen)
    text = (
        "Let's have a relaxed spoken conversation in English for about ten minutes. "
        "You lead: start right away with a question about my work or my week, ask one question "
        "at a time, keep your turns short and follow up on what I say.\n\n"
        "Steer the conversation so that I naturally need to talk about these kinds of things, "
        "without telling me that you are doing it:\n"
        f"{lines}\n\n"
        "Do not correct me while we talk. When I say \"feedback please\", list up to five "
        "grammar mistakes I made, each with what I said and a natural corrected version."
    )
    return {"text": text, "skills": [{"id": s["id"], "meaning": s["meaning"]} for s in chosen]}


def review_transcript(db: Session, text: str) -> dict | None:
    """Wyciąga z wklejonej rozmowy błędy uczącego się i robi z nich zadania."""
    catalogue = "\n".join(
        f"- {s['id']}: {s['meaning']} -> {s['pattern']}" for s in skills.all_skills()
    )
    review = llm.complete_json(
        "review_transcript",
        {"catalogue": catalogue, "transcript": text},
        llm.TranscriptReview,
        model=get_settings().openai_grammar_model or None,
        timeout=GENERATE_TIMEOUT_S,
        temperature=0.0,
    )
    if review is None:
        return None
    rows = skills.ensure_rows(db)
    today = local_today()
    findings = []
    for f in review.findings[:12]:
        said, corrected = f.said.strip(), f.corrected.strip()
        if not said or not corrected or said.lower() == corrected.lower():
            continue
        sdef = skills.skill_def(f.skill_id)
        if sdef is not None:
            db.add(
                GrammarBankItem(
                    skill_id=f.skill_id, fmt="own", prompt=said, model_answer=corrected,
                    hint=f.explanation.strip(), accepted_variants=[], source="transcript",
                )
            )
            row = rows[f.skill_id]
            if row.level == skills.NEW:
                # prawdziwy błąd w rozmowie to lepsza sonda niż jakiekolwiek zadanie
                row.level, row.streak = skills.LEARNING, 0
            elif row.level >= skills.SOLID:
                row.next_due = today.isoformat()
        findings.append(
            {
                "skill_id": f.skill_id if sdef else None,
                "skill_label": sdef["meaning"] if sdef else None,
                "said": said,
                "corrected": corrected,
                "explanation": f.explanation.strip(),
            }
        )
    used_well = []
    for sid in dict.fromkeys(review.used_well):
        sdef = skills.skill_def(sid)
        if sdef is None:
            continue
        rows[sid].wild_uses += 1
        used_well.append({"skill_id": sid, "label": sdef["meaning"]})
    db.commit()
    return {"findings": findings, "used_well": used_well, "summary": review.summary.strip()}
