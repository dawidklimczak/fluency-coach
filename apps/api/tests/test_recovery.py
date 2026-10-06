"""Test integracyjny Recovery Drill (spec zmian §8)."""

import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import llm


def silence_wav_bytes(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setattr(llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        llm, "complete_json",
        lambda prompt_name, variables, schema: llm.GeneratedFollowUp(question="Could you give me an example?"),
    )


def _post_attempt(c: TestClient, url: str, meta: dict) -> dict:
    files = {"audio": ("attempt.wav", silence_wav_bytes(), "audio/wav")}
    data = {"payload": json.dumps(meta)}
    r = c.post(url, files=files, data=data)
    assert r.status_code == 202, r.text
    return r.json()


def test_static_trial_kinds_have_prompts():
    with TestClient(app) as c:
        for kind in ("lost_thread", "reformulation"):
            r = c.get(f"/api/recovery/trials/{kind}")
            assert r.status_code == 200
            assert r.json()["prompt"]
            assert r.json()["speaking_limit_seconds"] == 30


def test_full_recovery_flow(mock_llm):
    with TestClient(app) as c:
        lost_thread = _post_attempt(
            c, "/api/recovery/trials/lost_thread/attempts", {"t0_offset_samples": 0}
        )
        status = c.get(f"/api/recovery/attempts/{lost_thread['attempt_id']}").json()
        assert status["status"] == "done"

        reformulation = _post_attempt(
            c, "/api/recovery/trials/reformulation/attempts", {"t0_offset_samples": 0}
        )
        assert c.get(f"/api/recovery/attempts/{reformulation['attempt_id']}").json()["status"] == "done"

        follow_up = c.post(
            "/api/recovery/follow-up", json={"lost_thread_attempt_id": lost_thread["attempt_id"]}
        )
        assert follow_up.status_code == 200, follow_up.text
        body = follow_up.json()
        assert set(body.keys()) == {"recovery_attempt_id", "question"}
        assert body["question"] == "Could you give me an example?"

        final = _post_attempt(
            c,
            f"/api/recovery/follow-up/{body['recovery_attempt_id']}/attempts",
            {"t0_offset_samples": 0},
        )
        assert c.get(f"/api/recovery/attempts/{final['attempt_id']}").json()["status"] == "done"


def test_follow_up_without_prior_lost_thread_returns_404():
    with TestClient(app) as c:
        r = c.post("/api/recovery/follow-up", json={"lost_thread_attempt_id": 999999})
        assert r.status_code == 404


def test_invalid_kind_rejected():
    with TestClient(app) as c:
        r = c.get("/api/recovery/trials/clarification_followup")
        assert r.status_code == 422
