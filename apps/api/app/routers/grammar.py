"""Grammar: krótkie mówione rundy, ocena po każdej odpowiedzi, mapa umiejętności.

Runda składa się z banku zadań bez wywołań LLM. Każda odpowiedź jest
transkrybowana i oceniana w tle zaraz po nagraniu, więc przerwanie rundy
niczego nie traci. Nagrania są kasowane od razu po analizie.
"""

import json
import logging
import tempfile

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import GrammarAnswer, GrammarRound
from ..services import grammar as grammar_svc
from ..services import llm
from ..services import shadow as shadow_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/grammar", tags=["grammar"])

MAX_TRANSCRIPT_CHARS = 40_000


def _get_round(db: Session, round_id: int) -> GrammarRound:
    rnd = db.get(GrammarRound, round_id)
    if rnd is None:
        raise HTTPException(404, "Nie ma takiej rundy")
    return rnd


def _entry(rnd: GrammarRound, index: int) -> dict:
    for e in rnd.plan:
        if e["index"] == index:
            return e
    raise HTTPException(404, "Nie ma takiego zadania w tej rundzie")


@router.get("/home")
def home(background: BackgroundTasks, db: Session = Depends(get_db)):
    # wejście na ekran startowy to dobry moment, żeby w tle uzupełnić bank
    background.add_task(grammar_svc.top_up)
    # ...i przygotować fragmenty do shadowingu, żeby wejście tam nie czekało
    background.add_task(shadow_svc.ensure_stock)
    return grammar_svc.home(db)


@router.get("/map")
def skill_map(db: Session = Depends(get_db)):
    return grammar_svc.map_payload(db)


@router.post("/rounds")
def create_round(background: BackgroundTasks, db: Session = Depends(get_db)):
    rnd = grammar_svc.create_round(db)
    if rnd is None:
        if not llm.llm_enabled():
            raise HTTPException(503, "Brak klucza OpenAI - ustaw go w Ustawieniach")
        # pusty bank (brak pliku startowego): generujemy w tle, klient ponawia
        background.add_task(grammar_svc.top_up)
        raise HTTPException(409, "Bank zadań jest jeszcze pusty - przygotowuję ćwiczenia")
    background.add_task(grammar_svc.top_up)
    return grammar_svc.round_payload(db, rnd)


@router.get("/rounds/{round_id}")
def get_round(round_id: int, db: Session = Depends(get_db)):
    return grammar_svc.round_payload(db, _get_round(db, round_id))


@router.post("/rounds/{round_id}/answers", status_code=202)
async def submit_answer(
    round_id: int,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form(...),
    db: Session = Depends(get_db),
):
    rnd = _get_round(db, round_id)
    try:
        meta = json.loads(payload)
        index = int(meta["index"])
        hint_used = bool(meta.get("hint_used", False))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")
    entry = _entry(rnd, index)

    answer = GrammarAnswer(
        round_id=rnd.id, entry_index=index, item_id=entry["item_id"],
        skill_id=entry["skill_id"], kind=entry["kind"], fmt=entry["fmt"],
        hint_used=hint_used, skipped=False,
    )
    db.add(answer)
    db.commit()

    fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="grammar-")
    with open(fd, "wb") as f:
        f.write(await audio.read())
    background.add_task(grammar_svc.process_answer, answer.id, temp_path)
    return {"answer_id": answer.id}


class SkipBody(BaseModel):
    index: int


@router.post("/rounds/{round_id}/skip")
def skip(round_id: int, body: SkipBody, db: Session = Depends(get_db)):
    rnd = _get_round(db, round_id)
    answer = grammar_svc.record_skip(db, rnd, _entry(rnd, body.index))
    return grammar_svc.answer_payload(answer)


@router.get("/answers/{answer_id}")
def get_answer(answer_id: int, db: Session = Depends(get_db)):
    answer = db.get(GrammarAnswer, answer_id)
    if answer is None:
        raise HTTPException(404, "Nie ma takiej odpowiedzi")
    return grammar_svc.answer_payload(answer)


class ExtraBody(BaseModel):
    skill_id: str


@router.post("/rounds/{round_id}/extra")
def extra(round_id: int, body: ExtraBody, db: Session = Depends(get_db)):
    """Dokłada na koniec rundy jeszcze jedno zadanie z umiejętności, w której padł błąd."""
    rnd = _get_round(db, round_id)
    entry = grammar_svc.add_extra(db, rnd, body.skill_id)
    return {"entry": grammar_svc.entry_payload(db, entry) if entry else None}


@router.post("/rounds/{round_id}/end")
def end_round(round_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    rnd = _get_round(db, round_id)
    summary = grammar_svc.finish_round(db, rnd)
    background.add_task(grammar_svc.top_up)
    return {"round_id": rnd.id, "summary": summary, "home": grammar_svc.home(db)}


@router.get("/talk-prompt")
def talk_prompt(db: Session = Depends(get_db)):
    return grammar_svc.talk_prompt(db)


class TranscriptBody(BaseModel):
    text: str = Field(min_length=1)


@router.post("/transcript")
def review_transcript(body: TranscriptBody, db: Session = Depends(get_db)):
    if not llm.llm_enabled():
        raise HTTPException(503, "Brak klucza OpenAI - ustaw go w Ustawieniach")
    text = body.text.strip()
    if len(text) < 40:
        raise HTTPException(422, "Za mało tekstu - wklej zapis całej rozmowy")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[-MAX_TRANSCRIPT_CHARS:]
    result = grammar_svc.review_transcript(db, text)
    if result is None:
        raise HTTPException(502, "Nie udało się przeanalizować rozmowy, spróbuj jeszcze raz")
    return result
