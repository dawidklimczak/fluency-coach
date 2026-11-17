"""Shadowing: mówienie razem z nagraniem wzorcowym.

Tekst pisze LLM pod umiejętności gramatyczne, które są akurat w toku, głos
pochodzi z syntezy mowy (powstaje raz i zostaje na dysku), a czasy słów we
wzorcu z transkrypcji tego nagrania.

Mierzymy tylko to, co da się zmierzyć rzetelnie: ile słów użytkownik nadążył
powiedzieć, w którym zdaniu odpadł i czy opóźnienie względem lektora rosło.
Wymowy, akcentu ani intonacji NIE oceniamy - rozpoznawanie mowy tego nie
potrafi; do tego służy odsłuch własnego nagrania zaraz po lektorze.
"""

import logging
import random
import re
import statistics
import threading
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import db_session
from ..models import ShadowAttempt, ShadowPassage
from . import grammar as grammar_svc
from . import llm, reading, skills, transcription, vad
from .app_settings import openai_api_key

logger = logging.getLogger(__name__)

VOICES = ("ash", "coral", "sage", "verse")
VOICE_STYLE = (
    "Speak like a relaxed native speaker talking to a colleague: natural conversational "
    "pace, clear articulation, lively but unforced intonation. Do not sound like an announcer."
)
MIN_WORDS, MAX_WORDS = 60, 85
MAX_SKILLS = 3
UNCLEAR_SIMILARITY = 0.6  # poniżej tego podobieństwa "inne słowo" liczymy jako pominięte
STOCK_UNUSED = 2  # tyle nieużytych fragmentów trzymamy w zapasie
TTS_TIMEOUT_S = 90
LLM_TIMEOUT_S = 120

_stock_lock = threading.Lock()


# --- generowanie fragmentu -------------------------------------------------------


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def synthesize(text: str, voice: str, out_path: Path) -> bool:
    """Synteza mowy do pliku mp3. False = brak klucza albo błąd API."""
    key = openai_api_key()
    if not key:
        return False
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, timeout=TTS_TIMEOUT_S)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with client.audio.speech.with_streaming_response.create(
            model=get_settings().openai_tts_model,
            voice=voice,
            input=text,
            instructions=VOICE_STYLE,
            response_format="mp3",
        ) as response:
            response.stream_to_file(out_path)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        logger.exception("Synteza mowy nie powiodła się")
        return False


def reference_timing(text: str, spoken_words: list[dict]) -> tuple[list[dict], list[dict]]:
    """Słowa tekstu z czasami we wzorcu + zakresy czasowe zdań.

    Czasy pochodzą z transkrypcji nagrania wzorcowego. Słowa, których
    rozpoznawanie nie dopasowało, dostają czas przez interpolację między
    sąsiadami - wzorzec przeczytał cały tekst, więc każde słowo gdzieś jest.
    """
    sentences = split_sentences(text)
    tokens: list[dict] = []
    for s_index, sentence in enumerate(sentences):
        for t in reading.tokenize_reference(sentence):
            tokens.append({"text": t["text"], "norm": t["norm"], "sentence": s_index})
    aligned, _ = reading.align(
        [{"text": t["text"], "norm": t["norm"], "newline_before": False} for t in tokens],
        spoken_words,
    )
    for t, a in zip(tokens, aligned):
        t["start"], t["end"] = a["start"], a["end"]

    total = max((w["end"] for w in spoken_words), default=0.0)
    n = len(tokens)
    i = 0
    while i < n:
        if tokens[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < n and tokens[j]["start"] is None:
            j += 1
        left = tokens[i - 1]["end"] if i > 0 else 0.0
        right = tokens[j]["start"] if j < n else total
        step = (right - left) / (j - i) if j > i else 0.0
        for k in range(i, j):
            tokens[k]["start"] = round(left + step * (k - i), 3)
            tokens[k]["end"] = round(left + step * (k - i + 1), 3)
        i = j

    ranges = []
    for s_index, sentence in enumerate(sentences):
        own = [t for t in tokens if t["sentence"] == s_index]
        if not own:
            continue
        ranges.append(
            {"index": s_index, "text": sentence, "start": own[0]["start"], "end": own[-1]["end"]}
        )
    return tokens, ranges


def _target_skills(db: Session) -> list[dict]:
    rows = skills.ensure_rows(db)
    defs = skills.all_skills()
    active = [s for s in defs if rows[s["id"]].level in (skills.LEARNING, skills.UNAIDED)]
    active.sort(key=lambda s: rows[s["id"]].last_seen or "", reverse=True)
    if len(active) > MAX_SKILLS:
        # dwie najświeższe i jedna losowa z reszty, żeby fragmenty się różniły
        active = active[:2] + [random.choice(active[2:])]
    return active or [s for s in defs if rows[s["id"]].level == skills.NEW][:MAX_SKILLS] or defs[:MAX_SKILLS]


def generate_passage(db: Session) -> ShadowPassage | None:
    """Tekst (LLM) -> nagranie (synteza) -> czasy słów (transkrypcja)."""
    chosen = _target_skills(db)
    used = [p.title for p in db.query(ShadowPassage).order_by(ShadowPassage.id.desc()).limit(15)]
    generated = llm.complete_json(
        "generate_shadow_passage",
        {
            "context": grammar_svc._context(db),
            "used_titles": "; ".join(used) if used else "(none yet)",
            "skill_lines": "\n".join(
                f"- {s['meaning']}: {s['pattern']} (for example: {s['example']})" for s in chosen
            ),
            "min_words": str(MIN_WORDS),
            "max_words": str(MAX_WORDS),
        },
        llm.GeneratedShadowPassage,
        model=get_settings().openai_grammar_model or None,
        timeout=LLM_TIMEOUT_S,
        temperature=0.9,
    )
    if generated is None:
        return None
    text = re.sub(r"\s+", " ", generated.text).strip()
    if len(text.split()) < 30:
        return None

    voice = random.choice(VOICES)
    audio_path = get_settings().shadow_audio_dir / f"{uuid.uuid4().hex}.mp3"
    if not synthesize(text, voice, audio_path):
        return None
    transcribed = transcription.transcribe(audio_path, prompt="")
    if not transcribed or not transcribed["words"]:
        audio_path.unlink(missing_ok=True)
        return None
    words, sentences = reference_timing(text, transcribed["words"])

    passage = ShadowPassage(
        title=generated.title.strip() or "Passage",
        text=text,
        skill_ids=[s["id"] for s in chosen],
        voice=voice,
        audio_path=str(audio_path),
        duration_s=round(max(w["end"] for w in transcribed["words"]), 2),
        words=words,
        sentences=sentences,
    )
    db.add(passage)
    db.commit()
    return passage


def _usable(p: ShadowPassage) -> bool:
    return bool(p.audio_path) and Path(p.audio_path).exists()


def next_passage(db: Session, exclude_id: int | None = None) -> ShadowPassage | None:
    """Najmniej używany gotowy fragment; gdy brak - generuje nowy (kilkanaście sekund)."""
    ready = [p for p in db.query(ShadowPassage).all() if _usable(p) and p.id != exclude_id]
    unused = [p for p in ready if p.times_used == 0]
    if unused:
        return min(unused, key=lambda p: p.id)
    fresh = generate_passage(db)
    if fresh is not None:
        return fresh
    return min(ready, key=lambda p: (p.times_used, p.id)) if ready else None


def ensure_stock() -> None:
    """W tle: dba, żeby następne wejście w shadowing nie czekało na generowanie."""
    if not llm.llm_enabled() or not _stock_lock.acquire(blocking=False):
        return
    db = db_session()
    try:
        unused = [p for p in db.query(ShadowPassage).all() if _usable(p) and p.times_used == 0]
        for _ in range(max(0, STOCK_UNUSED - len(unused))):
            if generate_passage(db) is None:
                break
    except Exception:
        logger.exception("Przygotowanie fragmentów do shadowingu nie powiodło się")
    finally:
        db.close()
        _stock_lock.release()


def passage_payload(p: ShadowPassage) -> dict:
    labels = [(skills.skill_def(sid) or {}).get("meaning", sid) for sid in (p.skill_ids or [])]
    return {
        "passage_id": p.id,
        "title": p.title,
        "text": p.text,
        "duration_s": p.duration_s,
        "audio_url": f"/api/shadow/passages/{p.id}/audio",
        "words": [
            {"text": w["text"], "sentence": w["sentence"], "start": w["start"], "end": w["end"]}
            for w in (p.words or [])
        ],
        "sentences": p.sentences or [],
        "skills": labels,
    }


# --- analiza podejścia -------------------------------------------------------------


def _sounds_like(expected: str, heard: str) -> bool:
    """Czy rozpoznane słowo jest zniekształconą wersją oczekiwanego (np. sorts / sort)."""
    return SequenceMatcher(None, expected, reading.normalize(heard)).ratio() >= UNCLEAR_SIMILARITY


def analyse(passage: ShadowPassage, spoken_words: list[dict], offset_s: float, speed: float) -> tuple[list[dict], dict]:
    """Porównuje to, co padło, z tekstem wzorca. Zwraca (słowa ze statusem, metryki).

    offset_s = moment startu odtwarzania wzorca w nagraniu użytkownika.
    """
    ref = passage.words or []
    aligned, _extra = reading.align(
        [{"text": w["text"], "norm": w["norm"], "newline_before": False} for w in ref], spoken_words
    )
    words = []
    lags: list[float] = []
    for r, a in zip(ref, aligned):
        if a["status"] == reading.STATUS_UNCLEAR and not _sounds_like(r["norm"], a.get("heard", "")):
            # dopasowanie sparowało to słowo z czymś zupełnie innym - to nie "niewyraźnie",
            # tylko "nie padło"; inaczej zgubione zdanie wyglądałoby jak prawie trafione
            a = {**a, "status": reading.STATUS_MISSED, "start": None, "end": None}
        lag = None
        if a["status"] == reading.STATUS_SPOKEN and a["start"] is not None:
            # czas słowa we wzorcu skaluje się z prędkością odtwarzania
            lag = round(a["start"] - offset_s - r["start"] / speed, 3)
            lags.append(lag)
        words.append(
            {
                "text": r["text"], "sentence": r["sentence"], "status": a["status"],
                "start": a["start"], "end": a["end"], "lag": lag,
            }
        )

    total = len(words)
    said = sum(1 for w in words if w["status"] == reading.STATUS_SPOKEN)
    near = sum(1 for w in words if w["status"] == reading.STATUS_UNCLEAR)

    per_sentence = []
    for s in passage.sentences or []:
        own = [w for w in words if w["sentence"] == s["index"]]
        if not own:
            continue
        hit = sum(1 for w in own if w["status"] == reading.STATUS_SPOKEN)
        timed = [w for w in own if w["start"] is not None]
        per_sentence.append(
            {
                "index": s["index"],
                "words": len(own),
                "said": hit,
                "coverage": round(hit / len(own), 3),
                # zakres w nagraniu użytkownika - do odsłuchu własnej wersji zdania
                "user_start": timed[0]["start"] if timed else None,
                "user_end": timed[-1]["end"] if timed else None,
            }
        )

    # najtrudniejsze zdanie: najniższe pokrycie; przy remisie dłuższe (więcej do zyskania)
    hardest = None
    candidates = [s for s in per_sentence if s["words"] >= 4 and s["coverage"] < 1.0]
    if candidates:
        hardest = min(candidates, key=lambda s: (s["coverage"], -s["words"]))["index"]

    lag_median = lag_drift = None
    if len(lags) >= 6:
        lag_median = round(statistics.median(lags), 2)
        third = max(2, len(lags) // 3)
        lag_drift = round(statistics.median(lags[-third:]) - statistics.median(lags[:third]), 2)

    metrics = {
        "total_words": total,
        "said": said,
        "unclear": near,
        "missed": total - said - near,
        "coverage": round(said / total, 3) if total else None,
        "sentences": per_sentence,
        "hardest_sentence": hardest,
        "lag_median_s": lag_median,
        "lag_drift_s": lag_drift,
        "transcript_missing": not spoken_words,
    }
    return words, metrics


def process_attempt(attempt_id: int, audio_path: str, offset_s: float) -> None:
    db = db_session()
    path = Path(audio_path)
    try:
        attempt = db.get(ShadowAttempt, attempt_id)
        passage = db.get(ShadowPassage, attempt.passage_id) if attempt else None
        if attempt is None or passage is None:
            return
        audio = vad.read_wav_mono16k(path)
        segments = vad.get_vad().speech_segments(audio)
        spoken: list[dict] = []
        if segments:
            # pusty prompt: nie podpowiadamy tekstu, żeby rozpoznawanie nie "usłyszało" wzorca
            transcribed = transcription.transcribe(path, prompt="")
            spoken = transcribed["words"] if transcribed else []
        words, metrics = analyse(passage, spoken, offset_s, attempt.speed or 1.0)
        attempt.words, attempt.metrics, attempt.status = words, metrics, "done"
        db.commit()
    except Exception:
        logger.exception("Analiza shadowingu %s nie powiodła się", attempt_id)
        db.rollback()
        attempt = db.get(ShadowAttempt, attempt_id)
        if attempt:
            attempt.status = "error"
            db.commit()
    finally:
        db.close()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Nie udało się usunąć pliku tymczasowego %s", path)
