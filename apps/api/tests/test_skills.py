"""Reguły poziomów umiejętności - czysta logika, bez nagrań i LLM."""

from datetime import date, timedelta

from app.models import GrammarSkill
from app.services import skills

D = date(2026, 11, 16)


def _skill(level=0, streak=0, **kw) -> GrammarSkill:
    base = dict(skill_id="x", level=level, streak=streak, lapses=0, interval_idx=0,
                attempts=0, correct=0, wild_uses=0, next_due=None)
    base.update(kw)
    return GrammarSkill(**base)


def test_catalogue_is_consistent():
    ids = [s["id"] for s in skills.all_skills()]
    assert len(ids) == len(set(ids)) and len(ids) >= 40
    group_ids = {g["id"] for g in skills.groups()}
    for s in skills.all_skills():
        assert s["group"] in group_ids
        assert s["meaning"] and s["pattern"] and s["example"] and s["pl"]


def test_probe_correct_skips_learning():
    s = _skill()
    assert skills.apply_answer(s, "correct", today=D) == (skills.NEW, skills.UNAIDED)
    assert s.streak == 1


def test_probe_wrong_or_avoided_starts_learning():
    for verdict in ("incorrect", "avoided"):
        s = _skill()
        skills.apply_answer(s, verdict, today=D)
        assert s.level == skills.LEARNING and s.streak == 0


def test_unclear_changes_nothing():
    s = _skill(level=skills.UNAIDED, streak=2)
    assert skills.apply_answer(s, "unclear", today=D) == (2, 2)
    assert s.streak == 2 and s.attempts == 0


def test_learning_goes_guided_then_situation_then_unaided():
    s = _skill(level=skills.LEARNING)
    assert skills.learning_fmt(s) == "guided"
    skills.apply_answer(s, "correct", today=D)
    skills.apply_answer(s, "correct", today=D)
    assert skills.learning_fmt(s) == "situation"
    # odpowiedź po podejrzeniu podpowiedzi nie przybliża do awansu
    skills.apply_answer(s, "correct", hint_used=True, today=D)
    assert s.streak == 2
    skills.apply_answer(s, "incorrect", today=D)
    assert s.streak == 1 and skills.learning_fmt(s) == "guided"
    for _ in range(3):
        skills.apply_answer(s, "correct", today=D)
    assert s.level == skills.UNAIDED and s.streak == 0


def test_unaided_needs_speed_or_longer_streak():
    s = _skill(level=skills.UNAIDED)
    for _ in range(4):
        skills.apply_answer(s, "correct", fast=False, today=D)
    assert s.level == skills.UNAIDED
    skills.apply_answer(s, "correct", fast=False, today=D)
    assert s.level == skills.SOLID

    s = _skill(level=skills.UNAIDED)
    for _ in range(3):
        skills.apply_answer(s, "correct", fast=True, today=D)
    assert s.level == skills.SOLID
    assert s.next_due == (D + timedelta(days=3)).isoformat()


def test_two_misses_in_a_row_bring_help_back():
    s = _skill(level=skills.UNAIDED, streak=2)
    skills.apply_answer(s, "incorrect", today=D)
    assert s.level == skills.UNAIDED and s.streak == 0
    skills.apply_answer(s, "avoided", today=D)
    assert s.level == skills.LEARNING
    assert skills.learning_fmt(s) == "situation"


def test_solid_survives_breaks_and_becomes_mastered():
    s = _skill(level=skills.SOLID, next_due=D.isoformat())
    day = D
    for gap in (7, 21):
        skills.apply_answer(s, "correct", today=day)
        assert s.level == skills.SOLID
        assert s.next_due == (day + timedelta(days=gap)).isoformat()
        day = day + timedelta(days=gap)
    skills.apply_answer(s, "correct", today=day)
    assert s.level == skills.MASTERED
    assert s.next_due == (day + timedelta(days=45)).isoformat()


def test_solid_not_due_does_not_advance():
    s = _skill(level=skills.SOLID, next_due=(D + timedelta(days=2)).isoformat())
    skills.apply_answer(s, "correct", today=D)
    assert s.interval_idx == 0 and s.next_due == (D + timedelta(days=2)).isoformat()
    skills.apply_answer(s, "incorrect", today=D)
    assert s.level == skills.SOLID and s.next_due == (D + timedelta(days=1)).isoformat()


def test_failed_review_drops_to_unaided():
    s = _skill(level=skills.SOLID, interval_idx=2, next_due=D.isoformat())
    skills.apply_answer(s, "incorrect", today=D)
    assert s.level == skills.UNAIDED and s.next_due is None


def test_mastered_miss_drops_one_level():
    s = _skill(level=skills.MASTERED, next_due=D.isoformat())
    skills.apply_answer(s, "incorrect", today=D)
    assert s.level == skills.SOLID and s.next_due == (D + timedelta(days=3)).isoformat()


def test_fast_threshold_grows_with_prompt_length():
    assert skills.fast_threshold_ms("one two three four") < skills.fast_threshold_ms("one two " * 10)
