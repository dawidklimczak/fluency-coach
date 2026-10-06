"""Test integracyjny Bottleneck Diagnostic (spec zmian §2)."""

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
    from app.services import diagnostics as diagnostics_svc

    monkeypatch.setattr(llm, "llm_enabled", lambda: True)
    # testy nie sprawdzają walidacji słownictwa (to już pokryte przez
    # test_pack_gen.py) - unikamy przypadkowego odrzucenia przez rzadkie słowa
    monkeypatch.setattr(diagnostics_svc, "unknown_words", lambda text, known: [])

    def fake_complete_json(prompt_name, variables, schema):
        if prompt_name == "diagnostic_prompt_set":
            return llm.GeneratedDiagnosticPromptSet(
                cold="Are cities getting too crowded?",
                supplied_ideas_prompt="Are social media good for tourism?",
                supplied_ideas=["visibility", "local economy", "overtourism"],
                self_plan="Should public transport be free?",
                native_control="Czy praca zdalna jest lepsza niż praca w biurze?",
            )
        if prompt_name == "recovery_followup":
            return llm.GeneratedFollowUp(question="Could you give me an example?")
        raise AssertionError(f"unexpected prompt {prompt_name}")

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)


def _post_attempt(c: TestClient, url: str, meta: dict) -> dict:
    files = {"audio": ("attempt.wav", silence_wav_bytes(), "audio/wav")}
    data = {"payload": json.dumps(meta)}
    r = c.post(url, files=files, data=data)
    assert r.status_code == 202, r.text
    return r.json()


def test_full_diagnostic_flow_with_native_control(mock_llm):
    with TestClient(app) as c:
        start = c.post("/api/diagnostics/start", json={"language_control_enabled": True})
        assert start.status_code == 200, start.text
        pack = start.json()
        session_id = pack["session_id"]
        conditions = [t["condition"] for t in pack["trials"]]
        assert conditions == ["cold", "supplied_ideas", "self_plan", "repetition", "native_control"]
        assert pack["note"] is None

        supplied = next(t for t in pack["trials"] if t["condition"] == "supplied_ideas")
        assert supplied["support_json"]["ideas"] == ["visibility", "local economy", "overtourism"]

        self_plan = next(t for t in pack["trials"] if t["condition"] == "self_plan")
        repetition = next(t for t in pack["trials"] if t["condition"] == "repetition")
        assert repetition["source_trial_id"] == self_plan["id"]
        assert repetition["prompt"] == self_plan["prompt"]

        plan = c.post(
            f"/api/diagnostics/{session_id}/plan",
            json={"trial_id": self_plan["id"], "items": ["public transport", "free"]},
        )
        assert plan.status_code == 200, plan.text

        for condition in conditions:
            res = _post_attempt(
                c, f"/api/diagnostics/{session_id}/trials/{condition}/attempts", {"t0_offset_samples": 0}
            )
            status = c.get(f"/api/diagnostics/attempts/{res['attempt_id']}").json()
            assert status["status"] == "done"

        end = c.post(f"/api/diagnostics/{session_id}/end")
        assert end.status_code == 200, end.text
        assert end.json()["status"] == "completed"
        assert end.json()["note"] is not None


def test_keyword_plan_limit_enforced(mock_llm):
    with TestClient(app) as c:
        session_id = c.post("/api/diagnostics/start", json={}).json()["session_id"]
        pack = c.get(f"/api/diagnostics/{session_id}").json()
        self_plan = next(t for t in pack["trials"] if t["condition"] == "self_plan")

        too_many = c.post(
            f"/api/diagnostics/{session_id}/plan",
            json={"trial_id": self_plan["id"], "items": ["a", "b", "c", "d"]},
        )
        assert too_many.status_code == 422


def test_bottleneck_profile_requires_three_sessions(mock_llm):
    with TestClient(app) as c:
        empty = c.get("/api/diagnostics/profile").json()
        assert empty["profile"] is None

        for _ in range(3):
            session_id = c.post("/api/diagnostics/start", json={}).json()["session_id"]
            pack = c.get(f"/api/diagnostics/{session_id}").json()
            for t in pack["trials"]:
                _post_attempt(
                    c,
                    f"/api/diagnostics/{session_id}/trials/{t['condition']}/attempts",
                    {"t0_offset_samples": 0},
                )
            c.post(f"/api/diagnostics/{session_id}/end")

        profile = c.get("/api/diagnostics/profile").json()["profile"]
        assert profile is not None
        assert profile["disclaimer"]
        assert profile["content_generation_sensitivity"] in ("high", "medium", "low", "unclear")


def test_native_control_trial_is_dispatched_with_skip_flag(mock_llm, monkeypatch):
    """Endpoint-level: condition='native_control' musi wołać process_attempt
    ze skip_language_metrics=True (jednostkowy test flagi samej jest w
    test_attempt_pipeline.py)."""
    from app.routers import diagnostics as diagnostics_router

    seen = {}

    def fake_process(attempt_id, skip_language_metrics=False):
        seen[attempt_id] = skip_language_metrics

    monkeypatch.setattr(
        diagnostics_router.attempt_pipeline, "process_attempt", fake_process
    )

    with TestClient(app) as c:
        session_id = c.post("/api/diagnostics/start", json={"language_control_enabled": True}).json()["session_id"]
        native_res = _post_attempt(
            c, f"/api/diagnostics/{session_id}/trials/native_control/attempts", {"t0_offset_samples": 0}
        )
        cold_res = _post_attempt(
            c, f"/api/diagnostics/{session_id}/trials/cold/attempts", {"t0_offset_samples": 0}
        )

    assert seen[native_res["attempt_id"]] is True
    assert seen[cold_res["attempt_id"]] is False
