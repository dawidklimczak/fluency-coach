"""Test integracyjny maszyny stanów sesji (spec §3-§4, dodatek v2).

LLM zamockowany (nie wywołuje prawdziwego API) - test sprawdza wiring:
start -> rundy -> sonda transferowa -> zamknięcie, bez oceny jakości treści.
Audio to cisza (VAD prawdziwy, model jest w repo) - Whisper nigdy nie jest
wołany (phonation poniżej progu), więc transkrypcja zostaje None wszędzie.
"""

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

    def fake_complete_json(prompt_name, variables, schema):
        if prompt_name == "generate_source_pack":
            return llm.GeneratedSourcePack(
                seed_text="I go home and cook dinner for my family every day after work.",
                guiding_questions=["What do I do after work?"],
                keywords=["home", "dinner", "family"],
                chunks=[llm.GeneratedChunk(text="cook dinner", prompt_pl="gotujesz kolację")],
                transfer_prompt="What do people in your country usually eat for dinner?",
                task_type="narrative",
                requires_personal_recall=False,
            )
        if prompt_name == "classify_transfer_outcome":
            return llm.TransferProbeOutcome(outcome="answered")
        if prompt_name == "far_transfer":
            return llm.GeneratedFarTransferPrompt(prompt="Should companies allow employees to work fully remotely?")
        raise AssertionError(f"unexpected prompt {prompt_name}")

    monkeypatch.setattr(llm, "complete_json", fake_complete_json)


def _post_attempt(c: TestClient, url: str, meta: dict) -> dict:
    files = {"audio": ("attempt.wav", silence_wav_bytes(), "audio/wav")}
    data = {"payload": json.dumps(meta)}
    r = c.post(url, files=files, data=data)
    assert r.status_code == 202, r.text
    return r.json()


def test_full_session_flow(mock_llm):
    with TestClient(app) as c:
        r = c.put("/api/profile/personal-context", json={"content": "Pracuję zdalnie jako programista."})
        assert r.status_code == 200

        r = c.post("/api/profile/domains", json={"name": "remote work", "target_sessions": 6})
        assert r.status_code == 200

        r = c.post("/api/speaking-sessions/start")
        assert r.status_code == 200, r.text
        pack = r.json()
        session_id = pack["session_id"]
        assert pack["support_ceiling"] == 4
        assert len(pack["rounds"]) == 4
        assert pack["rounds"][0]["support_level"] == 4
        assert pack["rounds"][0]["prep_s"] == 60
        assert pack["rounds"][-1]["support_level"] == 1
        assert pack["seed_text"]
        assert pack["rounds"][0]["speak_limit_s"] == 90
        assert pack["rounds"][-1]["speak_limit_s"] == 45
        assert sorted(pack["transfer_order"]) == ["far", "near"]
        assert pack["far_transfer_prompt"]

        plan = c.post(
            f"/api/speaking-sessions/{session_id}/keyword-plan",
            json={"items": ["visibility", "small businesses"]},
        )
        assert plan.status_code == 200, plan.text

        for round_number in range(1, 5):
            res = _post_attempt(
                c,
                f"/api/speaking-sessions/{session_id}/rounds/{round_number}/attempts",
                {"t0_offset_samples": 0},
            )
            attempt_id = res["attempt_id"]
            status = c.get(f"/api/speaking-sessions/attempts/{attempt_id}").json()
            assert status["status"] == "done"

        for probe_type in ("near", "far"):
            res = _post_attempt(
                c,
                f"/api/speaking-sessions/{session_id}/transfer-probe/{probe_type}",
                {"t0_offset_samples": 0},
            )
            status = c.get(f"/api/speaking-sessions/attempts/{res['attempt_id']}").json()
            assert status["status"] == "done"

        end = c.post(f"/api/speaking-sessions/{session_id}/end")
        assert end.status_code == 200, end.text
        summary = end.json()
        assert summary["ended_reason"] == "completed"
        assert summary["near"]["outcome_note"]
        assert summary["far"]["outcome_note"]
        assert "mean_length_of_run" in summary["near"]["deltas"]
        assert "mean_length_of_run" in summary["far"]["deltas"]

        domains = c.get("/api/profile/domains").json()
        assert domains[0]["session_count"] == 1


def test_start_without_active_domain_returns_409():
    with TestClient(app) as c:
        # domena z poprzedniego testu może już istnieć w tej samej bazie testowej
        # (SessionLocal dzieli plik) - test jest więc odporny, sprawdzamy tylko
        # że stan bez domeny daje 409, więc oznaczamy istniejącą jako done
        for d in c.get("/api/profile/domains").json():
            if d["status"] == "active":
                c.post(f"/api/profile/domains/{d['id']}/finish")
        r = c.post("/api/speaking-sessions/start")
        assert r.status_code == 409


def test_writing_rehearsal_requires_high_support(mock_llm):
    with TestClient(app) as c:
        for d in c.get("/api/profile/domains").json():
            if d["status"] == "active":
                c.post(f"/api/profile/domains/{d['id']}/finish")
        c.post("/api/profile/domains", json={"name": "cooking", "target_sessions": 6})
        r = c.post("/api/speaking-sessions/start")
        session_id = r.json()["session_id"]
        assert r.json()["writing_phase_active"] is True

        ok = c.post(
            f"/api/speaking-sessions/{session_id}/writing-rehearsal",
            json={"text": "I write about my day.", "duration_s": 120},
        )
        assert ok.status_code == 200
        assert ok.json()["word_count"] == 5


def test_chunk_access_exposure_records_rt(mock_llm):
    with TestClient(app) as c:
        for d in c.get("/api/profile/domains").json():
            if d["status"] == "active":
                c.post(f"/api/profile/domains/{d['id']}/finish")
        c.post("/api/profile/domains", json={"name": "travel", "target_sessions": 6})
        r = c.post("/api/speaking-sessions/start")
        pack = r.json()
        session_id = pack["session_id"]
        chunk_id = pack["bank_a_chunks"][0]["id"]

        res = c.post(
            f"/api/speaking-sessions/{session_id}/chunks/{chunk_id}/access", json={"rt_ms": 420}
        )
        assert res.status_code == 200
        assert res.json()["ok"] is True


def test_keyword_plan_respects_limits(mock_llm):
    with TestClient(app) as c:
        for d in c.get("/api/profile/domains").json():
            if d["status"] == "active":
                c.post(f"/api/profile/domains/{d['id']}/finish")
        c.post("/api/profile/domains", json={"name": "money", "target_sessions": 6})
        session_id = c.post("/api/speaking-sessions/start").json()["session_id"]

        too_many = c.post(
            f"/api/speaking-sessions/{session_id}/keyword-plan",
            json={"items": ["a", "b", "c", "d"]},
        )
        assert too_many.status_code == 422

        too_long = c.post(
            f"/api/speaking-sessions/{session_id}/keyword-plan",
            json={"items": ["this point has way too many words in it"]},
        )
        assert too_long.status_code == 422

        ok = c.post(
            f"/api/speaking-sessions/{session_id}/keyword-plan",
            json={"items": ["visibility", "overtourism"]},
        )
        assert ok.status_code == 200
        assert ok.json()["items"] == ["visibility", "overtourism"]


def test_far_transfer_probe_requires_prompt(mock_llm, monkeypatch):
    from app.services import transfer_probe as transfer_probe_svc

    monkeypatch.setattr(transfer_probe_svc, "generate_far_transfer_prompt", lambda db: None)

    with TestClient(app) as c:
        for d in c.get("/api/profile/domains").json():
            if d["status"] == "active":
                c.post(f"/api/profile/domains/{d['id']}/finish")
        c.post("/api/profile/domains", json={"name": "sports", "target_sessions": 6})
        pack = c.post("/api/speaking-sessions/start").json()
        session_id = pack["session_id"]
        assert pack["far_transfer_prompt"] is None

        files = {"audio": ("attempt.wav", silence_wav_bytes(), "audio/wav")}
        data = {"payload": json.dumps({"t0_offset_samples": 0})}
        res = c.post(
            f"/api/speaking-sessions/{session_id}/transfer-probe/far", files=files, data=data
        )
        assert res.status_code == 409

