"""Shadowing: czasy wzorca, analiza nadążania, przepływ przez API."""

import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.main import app
from app.models import ShadowAttempt, ShadowPassage
from app.services import llm, shadow, transcription, vad

TEXT = "I have been waiting for an hour. If I had known, I would have stayed home. Anyway, I will call you later."


DOUBLE = TEXT + " " + TEXT


def _words(text: str, start: float = 0.0, step: float = 0.4) -> list[dict]:
    """Udaje transkrypcję: każde słowo trwa `step` sekund, bez przerw."""
    out = []
    t = start
    for w in text.split():
        out.append({"word": w, "start": round(t, 3), "end": round(t + step, 3)})
        t += step
    return out


def _passage() -> ShadowPassage:
    words, sentences = shadow.reference_timing(TEXT, _words(TEXT))
    return ShadowPassage(
        title="Waiting", text=TEXT, voice="ash", words=words, sentences=sentences,
        duration_s=words[-1]["end"], skill_ids=["pp_since"], times_used=0,
    )


def wav_bytes(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * int(seconds * 16000))
    return buf.getvalue()


def test_reference_timing_covers_every_word_and_sentence():
    p = _passage()
    assert [s["index"] for s in p.sentences] == [0, 1, 2]
    assert len(p.words) == len(TEXT.split())
    assert all(w["start"] is not None and w["end"] is not None for w in p.words)
    assert p.sentences[0]["start"] == 0.0
    assert p.sentences[1]["start"] == pytest.approx(7 * 0.4)
    assert p.sentences[2]["end"] == pytest.approx(len(TEXT.split()) * 0.4)


def test_reference_timing_interpolates_words_the_recogniser_missed():
    spoken = [w for w in _words(TEXT) if w["word"] not in ("been", "waiting")]
    words, _ = shadow.reference_timing(TEXT, spoken)
    been, waiting = words[2], words[3]
    assert words[1]["end"] <= been["start"] < waiting["start"] < words[4]["start"]


def test_perfect_shadowing_has_full_coverage_and_steady_lag():
    p = _passage()
    # użytkownik mówi wszystko 0.5 s za lektorem; odtwarzanie ruszyło w 1.0 s nagrania
    spoken = _words(TEXT, start=1.5)
    words, m = shadow.analyse(p, spoken, offset_s=1.0, speed=1.0)
    assert m["coverage"] == 1.0 and m["missed"] == 0
    assert m["hardest_sentence"] is None
    assert m["lag_median_s"] == pytest.approx(0.5)
    assert m["lag_drift_s"] == pytest.approx(0.0)
    assert all(w["status"] == "spoken" for w in words)


def test_dropped_sentence_is_reported_as_hardest():
    p = _passage()
    kept = "I have been waiting for an hour. Anyway, I will call you later."
    words, m = shadow.analyse(p, _words(kept, start=1.2), offset_s=1.0, speed=1.0)
    assert m["hardest_sentence"] == 1
    by_index = {s["index"]: s for s in m["sentences"]}
    assert by_index[0]["coverage"] == 1.0 and by_index[1]["coverage"] < 0.3
    assert by_index[0]["user_start"] == pytest.approx(1.2)
    assert m["coverage"] < 1.0


def test_unrelated_words_count_as_missed_not_unclear():
    p = _passage()
    # w miejscu pierwszego zdania pada coś zupełnie innego, a "known" brzmi jak "know"
    said = "We are going to the cinema now. If I had know, I would have stayed home. Anyway, I will call you later."
    words, m = shadow.analyse(p, _words(said, start=1.2), offset_s=1.0, speed=1.0)
    first = [w for w in words if w["sentence"] == 0]
    assert all(w["status"] == "missed" for w in first if w["text"] not in ("I",))
    known = next(w for w in words if w["text"] == "known,")
    assert known["status"] == "unclear"
    assert m["hardest_sentence"] == 0


def test_lag_is_measured_against_slowed_reference():
    p = _passage()
    # przy 0.85x wzorzec trwa dłużej: słowo z t=4.0 s pada w 4.0/0.85 s odtwarzania
    spoken = [
        {"word": w["text"], "start": 1.0 + w["start"] / 0.85 + 0.3, "end": 1.0 + w["end"] / 0.85 + 0.3}
        for w in p.words
    ]
    _, m = shadow.analyse(p, spoken, offset_s=1.0, speed=0.85)
    assert m["lag_median_s"] == pytest.approx(0.3, abs=0.01)


def test_silence_gives_zero_coverage():
    _, m = shadow.analyse(_passage(), [], offset_s=0.0, speed=1.0)
    assert m["coverage"] == 0.0 and m["transcript_missing"] and m["lag_median_s"] is None


class _FakeVad:
    def speech_segments(self, audio, threshold=0.5):
        return [(0.5, 5.0)]


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Bez sieci: LLM, synteza i transkrypcja podmienione."""
    with TestClient(app):
        pass
    db = db_session()
    db.query(ShadowAttempt).delete()
    db.query(ShadowPassage).delete()
    db.commit()
    db.close()

    made: list[str] = []

    def fake_llm(prompt_name, variables, schema, **kwargs):
        assert prompt_name == "generate_shadow_passage"
        made.append(variables["skill_lines"])
        return llm.GeneratedShadowPassage(title=f"Story {len(made)}", text=DOUBLE)

    def fake_tts(text, voice, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp3")
        return True

    monkeypatch.setattr(llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake_llm)
    monkeypatch.setattr(shadow, "synthesize", fake_tts)
    monkeypatch.setattr(vad, "get_vad", lambda: _FakeVad())
    monkeypatch.setattr(
        transcription, "transcribe",
        lambda path, prompt=None: {"text": DOUBLE, "words": _words(DOUBLE, start=0.6)},
    )
    return made


def test_api_flow_generates_serves_and_analyses(stubbed):
    with TestClient(app) as c:
        p = c.get("/api/shadow/next").json()
        assert p["title"] == "Story 1" and len(p["sentences"]) == 6
        assert p["skills"] and p["words"][0]["start"] is not None
        audio = c.get(p["audio_url"])
        assert audio.status_code == 200 and audio.content == b"mp3"

        r = c.post(
            f"/api/shadow/passages/{p['passage_id']}/attempts",
            files={"audio": ("a.wav", wav_bytes(), "audio/wav")},
            data={"payload": json.dumps({"with_text": False, "speed": 0.85, "offset_s": 0.1})},
        )
        assert r.status_code == 202, r.text
        res = c.get(f"/api/shadow/attempts/{r.json()['attempt_id']}").json()
        assert res["status"] == "done" and res["with_text"] is False
        assert res["metrics"]["coverage"] == 1.0
        assert len(res["words"]) == len(p["words"])

        bad = c.post(
            f"/api/shadow/passages/{p['passage_id']}/attempts",
            files={"audio": ("a.wav", wav_bytes(), "audio/wav")},
            data={"payload": json.dumps({"speed": 3})},
        )
        assert bad.status_code == 422

        # zapas w tle: po pierwszym użyciu czekają już kolejne, nieużyte fragmenty
        nxt = c.get("/api/shadow/next").json()
        assert nxt["passage_id"] != p["passage_id"]
        assert len(stubbed) == 1 + shadow.STOCK_UNUSED

        other = c.get(f"/api/shadow/next?exclude={nxt['passage_id']}").json()
        assert other["passage_id"] not in (p["passage_id"], nxt["passage_id"])


def test_next_without_key_is_reported(stubbed, monkeypatch):
    monkeypatch.setattr(llm, "llm_enabled", lambda: False)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: None)
    with TestClient(app) as c:
        assert c.get("/api/shadow/next").status_code == 503
