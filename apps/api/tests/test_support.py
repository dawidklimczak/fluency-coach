"""Testy reguł wsparcia (spec §4) na izolowanej bazie w pamięci."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Attempt, Domain, FluencyMetrics, Round, SourcePack, SpeakingSession, SupportEvent, TransferProbe
from app.services import support


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_session(db, domain_id: int, ended: bool = True) -> SpeakingSession:
    pack = SourcePack(domain_id=domain_id, seed_text="x", status="validated")
    db.add(pack)
    db.flush()
    s = SpeakingSession(
        domain_id=domain_id, source_pack_id=pack.id, support_ceiling_at_start=4,
        ended_at="2026-01-01T00:00:00" if ended else None,
    )
    db.add(s)
    db.flush()
    return s


def _add_round_with_metrics(db, session_id: int, number: int, mean_length_of_run: float, duration_s: float = 150.0, speak_limit_s: int = 180):
    r = Round(session_id=session_id, number=number, support_level=4, prep_s=60, speak_limit_s=speak_limit_s)
    db.add(r)
    db.flush()
    a = Attempt(round_id=r.id, status="done", duration_s=duration_s)
    db.add(a)
    db.flush()
    fm = FluencyMetrics(attempt_id=a.id, mean_length_of_run=mean_length_of_run, phonation_time_ratio=duration_s / speak_limit_s)
    db.add(fm)
    db.commit()
    return r, a, fm


def _add_transfer_probe(
    db, session_id: int, mid_clause_pause_duration: float, mean_length_of_run: float,
    phonation_time_ratio: float, probe_type: str = "far",
):
    a = Attempt(status="done")
    db.add(a)
    db.flush()
    fm = FluencyMetrics(
        attempt_id=a.id,
        mid_clause_pause_duration=mid_clause_pause_duration,
        mean_length_of_run=mean_length_of_run,
        phonation_time_ratio=phonation_time_ratio,
    )
    db.add(fm)
    probe = TransferProbe(session_id=session_id, attempt_id=a.id, outcome="answered", probe_type=probe_type)
    db.add(probe)
    db.commit()
    return probe, fm


def test_no_change_during_calibration_period(db):
    domain = Domain(name="d")
    db.add(domain)
    db.flush()
    s = _make_session(db, domain.id)
    db.commit()
    event = support.evaluate_and_apply(db, s)
    assert event is None


def test_demotion_when_criteria_met_in_3_of_4_sessions(db):
    domain = Domain(name="d")
    db.add(domain)
    db.flush()

    # baseline sztucznie ustawiony wysoko, żeby próba <= 0.85x go spełniała
    support.push_baseline_value(db, "mid_clause_pause_duration", 1.0)
    db.commit()

    sessions = []
    for i in range(5):  # kalibracja (3) + 2 kolejne, żeby mieć >3 zakończone
        s = _make_session(db, domain.id)
        sessions.append(s)
    db.commit()

    # ostatnie 4 sesje: 3 spełniają kryteria (krótka pauza, dobry MLR), 1 nie
    for i, s in enumerate(sessions[-4:]):
        meets = i != 0  # pierwsza z tych 4 nie spełnia
        _add_round_with_metrics(db, s.id, 4, mean_length_of_run=5.0)
        if meets:
            _add_transfer_probe(db, s.id, mid_clause_pause_duration=0.5, mean_length_of_run=5.0, phonation_time_ratio=0.8)
        else:
            _add_transfer_probe(db, s.id, mid_clause_pause_duration=2.0, mean_length_of_run=5.0, phonation_time_ratio=0.8)

    event = support.evaluate_and_apply(db, sessions[-1])
    assert event is not None
    assert event.direction == "down"
    assert event.to_level == 3


def test_promotion_when_low_phonation_in_last_2_sessions(db):
    domain = Domain(name="d")
    db.add(domain)
    db.flush()

    support.push_baseline_value(db, "phonation_time_ratio", 0.9)
    db.commit()

    sessions = [_make_session(db, domain.id) for _ in range(4)]
    db.commit()
    # zejście do 2 wcześniej, żeby było gdzie wracać (na starcie ceiling=4=MAX)
    db.add(SupportEvent(session_id=sessions[0].id, from_level=3, to_level=2, direction="down", reason="test setup"))
    db.commit()

    for s in sessions[-2:]:
        _add_round_with_metrics(db, s.id, 4, mean_length_of_run=5.0, duration_s=170, speak_limit_s=180)
        _add_transfer_probe(db, s.id, mid_clause_pause_duration=1.0, mean_length_of_run=5.0, phonation_time_ratio=0.3)

    event = support.evaluate_and_apply(db, sessions[-1])
    assert event is not None
    assert event.direction == "up"
    assert event.to_level == 3


def test_near_and_far_baselines_do_not_mix(db):
    support.push_baseline_value(db, "mean_length_of_run", 10.0, probe_type="near")
    db.commit()
    assert support.get_baseline_median(db, "mean_length_of_run", "near") == 10.0
    assert support.get_baseline_median(db, "mean_length_of_run", "far") is None

    support.push_baseline_value(db, "mean_length_of_run", 3.0, probe_type="far")
    db.commit()
    assert support.get_baseline_median(db, "mean_length_of_run", "far") == 3.0
    assert support.get_baseline_median(db, "mean_length_of_run", "near") == 10.0


def test_update_baseline_ignores_legacy_probes(db):
    domain = Domain(name="d")
    db.add(domain)
    db.flush()
    s = _make_session(db, domain.id)
    db.commit()

    probe, _ = _add_transfer_probe(
        db, s.id, mid_clause_pause_duration=1.0, mean_length_of_run=5.0,
        phonation_time_ratio=0.8, probe_type="legacy",
    )
    support.update_baseline_from_transfer_probe(db, probe)
    assert support.get_baseline_median(db, "mean_length_of_run", "far") is None
    assert support.get_baseline_median(db, "mean_length_of_run", "near") is None
