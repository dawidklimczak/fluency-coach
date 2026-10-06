"""Test integracyjny modułu rozmowy (GPT-Live): sesja, zakończenie, metryki tur."""

import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import conversation
from app.services.conversation_pipeline import turn_metrics


def silence_wav_bytes(seconds: float = 6.0, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


@pytest.fixture
def mock_live(monkeypatch):
    captured = {}

    def fake_create(instructions, sdp_offer):
        captured["instructions"] = instructions
        captured["sdp_offer"] = sdp_offer
        return {"live_session_id": "live_test", "sdp": "SDP-ANSWER"}

    monkeypatch.setattr(conversation, "create_live_session", fake_create)
    return captured


def test_build_instructions_forbids_correction_and_seeds_chunks():
    text = conversation.build_instructions("colleague", "cloud migration", "I am a backend dev.", ["to be honest"])
    assert "NEVER correct" in text
    assert "cloud migration" in text
    assert "backend dev" in text
    assert '"to be honest"' in text


def test_start_rejects_unknown_persona(mock_live):
    with TestClient(app) as c:
        r = c.post("/api/conversation/start", json={"sdp_offer": "x", "persona": "robot"})
        assert r.status_code == 422


def test_start_returns_sdp_answer(mock_live):
    with TestClient(app) as c:
        r = c.post("/api/conversation/start", json={"sdp_offer": "OFFER", "persona": "colleague"})
        assert r.status_code == 201, r.text
        assert r.json()["sdp_answer"] == "SDP-ANSWER"
        assert mock_live["sdp_offer"] == "OFFER"


def test_start_maps_live_error_to_502(monkeypatch):
    def boom(instructions, sdp_offer):
        raise conversation.LiveSessionError("nope")

    monkeypatch.setattr(conversation, "create_live_session", boom)
    with TestClient(app) as c:
        r = c.post("/api/conversation/start", json={"sdp_offer": "x"})
        assert r.status_code == 502


def test_end_flow_produces_turns(mock_live):
    with TestClient(app) as c:
        sid = c.post("/api/conversation/start", json={"sdp_offer": "x"}).json()["session_id"]
        payload = {"turns": [{"start_s": 0.5, "end_s": 3.0}, {"start_s": 3.2, "end_s": 3.5}], "billed_seconds": 6}
        r = c.post(
            f"/api/conversation/{sid}/end",
            files={"audio": ("c.wav", silence_wav_bytes(), "audio/wav")},
            data={"payload": json.dumps(payload)},
        )
        assert r.status_code == 202, r.text
        body = c.get(f"/api/conversation/{sid}").json()
        assert body["status"] == "done"
        # druga tura (0.3 s) jest za krótka - pomijana jako back-channel/szum
        assert [t["number"] for t in body["turns"]] == [1]
        assert body["turns"][0]["metrics"]["phonation_time_ratio"] == 0.0
        assert c.post(
            f"/api/conversation/{sid}/end",
            files={"audio": ("c.wav", silence_wav_bytes(), "audio/wav")},
        ).status_code == 409


def test_turn_metrics_uses_only_words_in_window():
    words = [
        {"word": "before", "start": 0.1, "end": 0.5},
        {"word": "Hello", "start": 2.2, "end": 2.6},
        {"word": "there.", "start": 2.7, "end": 3.1},
        {"word": "after", "start": 6.0, "end": 6.4},
    ]
    m = turn_metrics([(2.2, 3.1)], words, (2.0, 4.0), [], [])
    assert m["transcript"] == "Hello there."
    assert m["ttfw"] == pytest.approx(0.2, abs=0.01)
