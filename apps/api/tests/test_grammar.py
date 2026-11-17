"""Grammar v2: rundy z banku, ocena po każdej odpowiedzi, mapa, most do rozmów."""

import io
import json
import wave
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import db_session
from app.main import app
from app.models import GrammarAnswer, GrammarBankItem, GrammarRound, GrammarSkill
from app.services import grammar, llm, shadow, skills, transcription, vad


def wav_bytes(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(seconds * sample_rate))
    return buf.getvalue()


class _FakeVad:
    def speech_segments(self, audio, threshold=0.5):
        return [(0.8, 2.0)]


def _round_id() -> int:
    db = db_session()
    try:
        return db.query(GrammarRound).order_by(GrammarRound.id.desc()).first().id
    finally:
        db.close()


@pytest.fixture
def clean_db():
    """Każdy test zaczyna z pustym postępem i małym bankiem dla 12 umiejętności."""
    with TestClient(app):
        pass  # init_db
    db = db_session()
    for model in (GrammarAnswer, GrammarRound, GrammarBankItem, GrammarSkill):
        db.query(model).delete()
    for s in skills.all_skills()[:12]:
        for n, fmt in enumerate(
            ("guided", "guided", "situation", "situation", "translate", "fix", "personal")
        ):
            db.add(
                GrammarBankItem(
                    skill_id=s["id"], fmt=fmt, prompt=f"{fmt} prompt {n} for {s['id']}",
                    cue="I have ..." if fmt == "guided" else "",
                    hint="meaning hint" if fmt == "situation" else "",
                    model_answer=s["example"], accepted_variants=[], source="seed",
                )
            )
    db.commit()
    db.close()


@pytest.fixture
def speech(monkeypatch):
    """Podmienia VAD, transkrypcję i LLM. verdicts[skill_id] steruje oceną."""
    verdicts: dict[str, str] = {}
    calls: list[tuple[str, dict]] = []

    def fake_llm(prompt_name, variables, schema, **kwargs):
        calls.append((prompt_name, variables))
        if schema is llm.GradedAnswer:
            sid = next(
                (s["id"] for s in skills.all_skills() if s["meaning"] == variables["meaning"]), ""
            )
            verdict = verdicts.get(sid, "correct")
            wrong = verdict != "correct"
            return llm.GradedAnswer(
                verdict=verdict,
                error_type="Wrong Shape" if wrong else "",
                explanation="Use the other shape." if wrong else "",
                note_pl="Po polsku inaczej." if wrong else "",
                corrected="Corrected sentence." if wrong else "",
                reaction="",
            )
        if schema is llm.TranscriptReview:
            return llm.TranscriptReview(
                findings=[
                    llm.TranscriptFinding(
                        skill_id="if_real", said="If I will have time, I will call.",
                        corrected="If I have time, I'll call.", explanation="No will after if.",
                    ),
                    llm.TranscriptFinding(
                        skill_id="nope", said="I go there yesterday.", corrected="I went there yesterday."
                    ),
                ],
                used_well=["pp_since", "pp_since", "bogus"],
                summary="Good flow.",
            )
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake_llm)
    monkeypatch.setattr(vad, "get_vad", lambda: _FakeVad())
    monkeypatch.setattr(transcription, "transcribe_text", lambda path: "I have known her for years.")
    # uzupełnianie banku w tle nie jest tematem tych testów
    monkeypatch.setattr(grammar, "top_up", lambda: 0)
    monkeypatch.setattr(shadow, "ensure_stock", lambda: None)
    return verdicts, calls


def _answer(c: TestClient, round_id: int, index: int, hint_used: bool = False) -> dict:
    r = c.post(
        f"/api/grammar/rounds/{round_id}/answers",
        files={"audio": ("a.wav", wav_bytes(), "audio/wav")},
        data={"payload": json.dumps({"index": index, "hint_used": hint_used})},
    )
    assert r.status_code == 202, r.text
    # TestClient wykonuje zadania w tle przed zwróceniem odpowiedzi
    return c.get(f"/api/grammar/answers/{r.json()['answer_id']}").json()


def test_first_round_probes_new_skills_without_help(clean_db, speech):
    with TestClient(app) as c:
        rnd = c.post("/api/grammar/rounds").json()
        entries = rnd["entries"]
        assert len(entries) == grammar.MAX_PROBES
        assert {e["kind"] for e in entries} == {"probe"}
        for e in entries:
            assert e["fmt"] in ("situation", "translate")
            assert e["cue"] == "" and e["hint"] == "" and not e["show_pattern"]
        # sondy biorą umiejętności w kolejności katalogu
        assert sorted(e["skill_id"] for e in entries) == sorted(
            s["id"] for s in skills.all_skills()[: grammar.MAX_PROBES]
        )


def test_answer_is_graded_at_once_and_moves_the_skill(clean_db, speech):
    verdicts, calls = speech
    with TestClient(app) as c:
        entries = c.post("/api/grammar/rounds").json()["entries"]
        rid = _round_id()
        good, bad = entries[0], entries[1]
        verdicts[bad["skill_id"]] = "incorrect"

        a = _answer(c, rid, good["index"])
        assert a["status"] == "done" and a["verdict"] == "correct"
        assert a["latency_ms"] == 800
        assert (a["level_before"], a["level_after"]) == (skills.NEW, skills.UNAIDED)
        assert a["explanation"] is None and a["corrected"] is None

        b = _answer(c, rid, bad["index"])
        assert b["verdict"] == "incorrect"
        assert b["error_type"] == "wrong shape"
        assert b["corrected"] == "Corrected sentence." and b["note_pl"] == "Po polsku inaczej."
        assert (b["level_before"], b["level_after"]) == (skills.NEW, skills.LEARNING)

        assert [name for name, _ in calls] == ["grade_grammar_answer"] * 2
        assert calls[0][1]["transcript"] == "I have known her for years."

        # błędne zadanie wraca w tej samej rundzie, teraz już z pomocą
        extra = c.post(
            f"/api/grammar/rounds/{rid}/extra", json={"skill_id": bad["skill_id"]}
        ).json()["entry"]
        assert extra["kind"] == "extra" and extra["fmt"] == "guided"
        assert extra["show_pattern"] and extra["cue"] == "I have ..." and extra["pattern"]
        assert extra["index"] == len(entries)

        end = c.post(f"/api/grammar/rounds/{rid}/end").json()
        assert end["summary"]["graded"] == 2 and end["summary"]["correct"] == 1
        moved = {m["skill_id"]: m for m in end["summary"]["moved"]}
        assert moved[good["skill_id"]]["up"] is True
        assert moved[bad["skill_id"]]["up"] is False
        assert end["summary"]["to_revisit"][0]["skill_id"] == bad["skill_id"]
        assert end["home"]["counts"]["unaided"] == 1 and end["home"]["counts"]["learning"] == 1
        assert end["home"]["week_days_done"] == 1


def test_extras_are_limited(clean_db, speech):
    with TestClient(app) as c:
        entries = c.post("/api/grammar/rounds").json()["entries"]
        rid = _round_id()
        sid = entries[0]["skill_id"]
        got = [
            c.post(f"/api/grammar/rounds/{rid}/extra", json={"skill_id": sid}).json()["entry"]
            for _ in range(grammar.MAX_EXTRAS + 1)
        ]
        assert got[0] is not None and got[1] is not None and got[2] is None
        prompts = {entries[0]["prompt"], got[0]["prompt"], got[1]["prompt"]}
        assert len(prompts) == 3  # za każdym razem inna sytuacja


def test_skip_counts_as_a_miss_without_llm(clean_db, speech):
    _, calls = speech
    with TestClient(app) as c:
        entries = c.post("/api/grammar/rounds").json()["entries"]
        rid = _round_id()
        r = c.post(f"/api/grammar/rounds/{rid}/skip", json={"index": entries[0]["index"]}).json()
        assert r["verdict"] == "incorrect" and r["corrected"] == entries[0]["model_answer"]
        assert r["level_after"] == skills.LEARNING
        assert calls == []
        assert c.post(f"/api/grammar/rounds/{rid}/skip", json={"index": 99}).status_code == 404


def test_silence_is_unclear_and_changes_nothing(clean_db, speech, monkeypatch):
    class Silent:
        def speech_segments(self, audio, threshold=0.5):
            return []

    monkeypatch.setattr(vad, "get_vad", lambda: Silent())
    with TestClient(app) as c:
        entries = c.post("/api/grammar/rounds").json()["entries"]
        a = _answer(c, _round_id(), entries[0]["index"])
        assert a["verdict"] == "unclear" and a["latency_ms"] is None
        assert a["level_after"] == skills.NEW


def test_round_mixes_reviews_learning_practice_and_probes(clean_db, speech):
    today = date.today()
    db = db_session()
    rows = skills.ensure_rows(db)
    ids = [s["id"] for s in skills.all_skills()]
    rows[ids[0]].level, rows[ids[0]].next_due = skills.SOLID, (today - timedelta(days=1)).isoformat()
    rows[ids[1]].level, rows[ids[1]].next_due = skills.SOLID, (today + timedelta(days=5)).isoformat()
    rows[ids[2]].level, rows[ids[2]].last_seen = skills.LEARNING, today.isoformat()
    rows[ids[3]].level = skills.UNAIDED
    rows[ids[4]].level = skills.UNAIDED
    db.commit()
    db.close()

    with TestClient(app) as c:
        home = c.get("/api/grammar/home").json()
        assert home["due_today"] == 1
        assert home["counts"] == {
            "new": len(ids) - 5, "learning": 1, "unaided": 2, "solid": 2, "mastered": 0,
        }
        entries = c.post("/api/grammar/rounds").json()["entries"]
        assert len(entries) == grammar.ROUND_SIZE
        by_kind: dict[str, list[str]] = {}
        for e in entries:
            by_kind.setdefault(e["kind"], []).append(e["skill_id"])
        # powtórka po przerwie otwiera rundę
        assert entries[0]["kind"] == "review" and by_kind["review"] == [ids[0]]
        assert by_kind["learn"] == [ids[2], ids[2]]
        assert sorted(by_kind["practice"]) == sorted([ids[3], ids[4]])
        assert len(by_kind["probe"]) == 3
        learn = [e for e in entries if e["kind"] == "learn"]
        assert all(e["fmt"] == "guided" and e["show_pattern"] for e in learn)
        assert len({e["prompt"] for e in entries}) == len(entries)


def test_no_probes_while_learning_backlog_is_full(clean_db, speech):
    db = db_session()
    rows = skills.ensure_rows(db)
    ids = [s["id"] for s in skills.all_skills()]
    for sid in ids[: grammar.LEARNING_BACKLOG_LIMIT]:
        rows[sid].level = skills.LEARNING
    db.commit()
    db.close()
    with TestClient(app) as c:
        entries = c.post("/api/grammar/rounds").json()["entries"]
        assert "probe" not in {e["kind"] for e in entries}
        learning = {e["skill_id"] for e in entries if e["kind"] == "learn"}
        assert len(learning) >= grammar.MAX_LEARNING_SKILLS


def test_empty_bank_reports_not_ready(clean_db, speech):
    db = db_session()
    db.query(GrammarBankItem).delete()
    db.commit()
    db.close()
    with TestClient(app) as c:
        assert c.post("/api/grammar/rounds").status_code == 409


def test_map_lists_every_skill_once(clean_db, speech):
    with TestClient(app) as c:
        groups = c.get("/api/grammar/map").json()["groups"]
        listed = [s["id"] for g in groups for s in g["skills"]]
        assert sorted(listed) == sorted(s["id"] for s in skills.all_skills())
        assert all(g["skills"] for g in groups)


def test_talk_prompt_uses_skills_in_progress(clean_db, speech):
    db = db_session()
    rows = skills.ensure_rows(db)
    rows["if_real"].level = skills.LEARNING
    db.commit()
    db.close()
    with TestClient(app) as c:
        body = c.get("/api/grammar/talk-prompt").json()
        assert [s["id"] for s in body["skills"]] == ["if_real"]
        assert skills.skill_def("if_real")["meaning"] in body["text"]
        assert "feedback please" in body["text"]


def test_transcript_review_creates_own_items_and_stars(clean_db, speech):
    with TestClient(app) as c:
        assert c.post("/api/grammar/transcript", json={"text": "short"}).status_code == 422
        r = c.post(
            "/api/grammar/transcript",
            json={"text": "You said: If I will have time, I will call. " * 3},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["findings"]) == 2
        assert body["findings"][0]["skill_id"] == "if_real"
        # błąd spoza mapy pokazujemy, ale nie robimy z niego zadania
        assert body["findings"][1]["skill_id"] is None
        assert body["used_well"] == [
            {"skill_id": "pp_since", "label": skills.skill_def("pp_since")["meaning"]}
        ]

    db = db_session()
    own = db.query(GrammarBankItem).filter(GrammarBankItem.fmt == "own").all()
    assert [(i.skill_id, i.prompt, i.model_answer) for i in own] == [
        ("if_real", "If I will have time, I will call.", "If I have time, I'll call.")
    ]
    # błąd z prawdziwej rozmowy zastępuje sondę: umiejętność od razu idzie do nauki
    assert db.get(GrammarSkill, "if_real").level == skills.LEARNING
    assert db.get(GrammarSkill, "pp_since").wild_uses == 1
    db.close()


def test_generated_items_are_filtered():
    ok = llm.GeneratedBankItem(
        fmt="guided", prompt="Your boss asks about Friday. What do you say?",
        cue="I'll ...", model_answer="I'll send it by Friday morning.",
    )
    assert grammar.valid_generated(ok)
    # początek zdania nie może zdradzać większości odpowiedzi
    assert not grammar.valid_generated(ok.model_copy(update={"cue": "I'll send it by ..."}))
    in_prompt = llm.GeneratedBankItem(
        fmt="situation", prompt="Say: I have known her for ten years.",
        model_answer="I have known her for ten years.",
    )
    assert not grammar.valid_generated(in_prompt)
    assert not grammar.valid_generated(ok.model_copy(update={"fmt": "essay"}))
    assert not grammar.valid_generated(ok.model_copy(update={"model_answer": " "}))
