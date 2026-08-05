"""Przepływ sesji nauki: otwarcie, wznowienie, powiązanie drilli, zamknięcie."""

from fastapi.testclient import TestClient

from app.main import app


def test_learning_session_flow():
    with TestClient(app) as c:
        # otwarcie
        r = c.post("/api/learning-sessions").json()
        ls_id = r["id"]
        assert r["resumed"] is False
        assert r["attempts"] == 0

        # ponowne otwarcie wznawia tę samą sesję
        r2 = c.post("/api/learning-sessions").json()
        assert r2["id"] == ls_id
        assert r2["resumed"] is True

        cur = c.get("/api/learning-sessions/current").json()
        assert cur["open"] is True and cur["id"] == ls_id

        # przebieg drilla powiązany z sesją nauki
        run = c.post(
            "/api/sessions",
            json={"module": "rapid_response", "learning_session_id": ls_id},
        ).json()
        assert "session_id" in run

        # zamknięcie: podsumowanie (bez prób -> puste, bez feedbacku LLM)
        end = c.post(f"/api/learning-sessions/{ls_id}/end").json()
        assert end["summary"]["number"] == ls_id
        assert end["summary"]["attempts"] == 0

        cur2 = c.get("/api/learning-sessions/current").json()
        assert cur2["open"] is False

        # ponowne zamknięcie zwraca zapisane podsumowanie
        again = c.post(f"/api/learning-sessions/{ls_id}/end").json()
        assert again["summary"]["number"] == ls_id


def test_end_unknown_session_404():
    with TestClient(app) as c:
        assert c.post("/api/learning-sessions/999999/end").status_code == 404
