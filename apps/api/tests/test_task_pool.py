"""Zużycie puli zadań: 3 pojawienia (rundy nie liczą się osobno) i zadanie wypada."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Attempt, Task, TrainingSession
from app.services.task_select import exhausted_task_ids, pick_task


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _use_task(db, task_id: str, session_id: int, rounds: int = 1):
    db.add(TrainingSession(id=session_id, user_id=1, module="rapid_response"))
    for r in range(1, rounds + 1):
        db.add(
            Attempt(
                session_id=session_id,
                task_id=task_id,
                attempt_index=1,
                round_index=r,
                status="done",
            )
        )
    db.commit()


def test_task_leaves_pool_after_three_uses(db):
    db.add(Task(id="rr_1", module="rapid_response", difficulty=1, prompt_text="q"))
    db.commit()

    for i in range(1, 3):
        _use_task(db, "rr_1", session_id=i)
    assert exhausted_task_ids(db) == set()
    assert pick_task(db, "rapid_response", 1, set()) is not None

    _use_task(db, "rr_1", session_id=3)
    assert exhausted_task_ids(db) == {"rr_1"}
    assert pick_task(db, "rapid_response", 1, set()) is None


def test_rounds_count_as_one_use(db):
    db.add(Task(id="pp_1", module="paraphrase", difficulty=1, prompt_text="q"))
    db.commit()

    # jeden przebieg z trzema rundami = jedno pojawienie
    _use_task(db, "pp_1", session_id=1, rounds=3)
    assert exhausted_task_ids(db) == set()


def test_exhausted_excluded_even_when_pool_would_be_empty(db):
    db.add(Task(id="rr_1", module="rapid_response", difficulty=1, prompt_text="q"))
    db.add(Task(id="rr_2", module="rapid_response", difficulty=1, prompt_text="q2"))
    db.commit()
    for i in range(1, 4):
        _use_task(db, "rr_1", session_id=i)

    picked = pick_task(db, "rapid_response", 1, set())
    assert picked is not None and picked.id == "rr_2"
