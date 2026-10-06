"""Rozmowa głosowa z GPT-Live. Ekran rozmowy nie pokazuje transkryptu ani korekt;
wyniki (metryki tur) są dostępne dopiero po zakończeniu."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import ConversationSession, ConversationTurn, Domain, PersonalContext, now_iso
from ..services import conversation, conversation_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversation", tags=["conversation"])


class StartBody(BaseModel):
    sdp_offer: str
    persona: str = "tutor"
    domain_id: int | None = None
    target_chunks: list[str] = Field(default_factory=list, max_length=3)
    max_minutes: int = Field(15, ge=1, le=30)


@router.get("/personas")
def list_personas():
    return {"personas": list(conversation.PERSONAS)}


@router.post("/start", status_code=201)
def start(body: StartBody, db: Session = Depends(get_db)):
    if body.persona not in conversation.PERSONAS:
        raise HTTPException(422, f"persona musi być jedną z: {', '.join(conversation.PERSONAS)}")
    domain = db.get(Domain, body.domain_id) if body.domain_id else None
    if body.domain_id and domain is None:
        raise HTTPException(404, "Nie ma takiej domeny")
    ctx = (
        db.query(PersonalContext)
        .filter(PersonalContext.active.is_(True))
        .order_by(PersonalContext.version.desc())
        .first()
    )
    instructions = conversation.build_instructions(
        body.persona, domain.name if domain else None, ctx.content if ctx else None, body.target_chunks
    )
    try:
        live = conversation.create_live_session(instructions, body.sdp_offer)
    except conversation.LiveSessionError as e:
        raise HTTPException(502, str(e))

    session = ConversationSession(
        domain_id=body.domain_id, persona=body.persona, target_chunks=body.target_chunks,
        live_session_id=live["live_session_id"], max_minutes=body.max_minutes,
    )
    db.add(session)
    db.commit()
    return {"session_id": session.id, "sdp_answer": live["sdp"], "max_minutes": session.max_minutes}


@router.post("/{session_id}/end", status_code=202)
async def end(
    session_id: int,
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    payload: str = Form("{}"),
    db: Session = Depends(get_db),
):
    """payload: {"turns": [{"start_s": .., "end_s": ..}], "billed_seconds": ..}
    start_s = koniec wypowiedzi rozmówcy, end_s = koniec wypowiedzi użytkownika
    (sekundy od początku nagrania mikrofonu)."""
    session = db.get(ConversationSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej rozmowy")
    if session.status != "active":
        raise HTTPException(409, "Rozmowa jest już zakończona")
    try:
        meta = json.loads(payload)
        windows = [(float(t["start_s"]), float(t["end_s"])) for t in meta.get("turns", [])]
        billed = meta.get("billed_seconds")
        billed = float(billed) if billed is not None else None
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"Niepoprawny payload: {e}")

    audio_dir = get_settings().audio_dir / "conversation"
    audio_dir.mkdir(parents=True, exist_ok=True)
    path = audio_dir / f"{session.id}.wav"
    path.write_bytes(await audio.read())

    session.audio_path = str(path)
    session.ended_at = now_iso()
    session.billed_seconds = billed
    session.status = "processing"
    db.commit()

    background.add_task(conversation_pipeline.process_conversation, session.id, windows)
    return {"session_id": session.id}


@router.get("/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(ConversationSession, session_id)
    if session is None:
        raise HTTPException(404, "Nie ma takiej rozmowy")
    turns = []
    if session.status == "done":
        rows = (
            db.query(ConversationTurn)
            .filter(ConversationTurn.session_id == session.id)
            .order_by(ConversationTurn.number)
            .all()
        )
        turns = [
            {"number": t.number, "start_s": t.start_s, "end_s": t.end_s, "metrics": t.metrics}
            for t in rows
        ]
    return {
        "session_id": session.id,
        "status": session.status,
        "persona": session.persona,
        "billed_seconds": session.billed_seconds,
        "turns": turns,
    }
