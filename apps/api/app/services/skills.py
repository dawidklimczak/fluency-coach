"""Mapa umiejętności gramatycznych: katalog i reguły poziomów.

Umiejętność = para znaczenie -> kształt zdania (np. "żałuję czegoś z
przeszłości" -> "if + had + past participle, would have + past participle").
Katalog leży w data/grammar_skills.json, postęp w tabeli grammar_skills.

Poziomy:
  0 NEW       jeszcze nie widziana
  1 LEARNING  z pomocą (widoczny kształt i początek zdania, potem sama sytuacja)
  2 UNAIDED   poprawnie z samej sytuacji, w rundach mieszanych
  3 SOLID     poprawnie i szybko; teraz musi przetrwać przerwy 3, 7 i 21 dni
  4 MASTERED  przetrwała wszystkie przerwy; kontrola co 45, potem co 90 dni

Ten moduł nie woła LLM ani bazy poza przekazanym obiektem - reguły są czyste,
żeby dało się je testować bez nagrań.
"""

import json
from datetime import date, timedelta
from functools import lru_cache

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import GrammarSkill, now_iso

NEW, LEARNING, UNAIDED, SOLID, MASTERED = 0, 1, 2, 3, 4
LEVEL_NAMES = {NEW: "new", LEARNING: "learning", UNAIDED: "unaided", SOLID: "solid", MASTERED: "mastered"}

# przerwy (dni), które umiejętność musi przetrwać na poziomie SOLID
REVIEW_INTERVALS = (3, 7, 21)
MASTERED_INTERVALS = (45, 90)

# LEARNING: tyle poprawnych pod rząd z widocznym kształtem, zanim zniknie
GUIDED_STREAK = 2
# LEARNING -> UNAIDED
LEARNING_STREAK = 4
# UNAIDED -> SOLID: tyle poprawnych pod rząd, ostatnia szybka...
SOLID_STREAK = 3
# ...albo tyle pod rząd bez względu na tempo (pomiar czasu bywa zaszumiony)
SOLID_STREAK_ANY_SPEED = 5
# dwa błędy pod rząd na UNAIDED = wracamy do pomocy
LAPSES_TO_RELEARN = 2

GRADED = ("correct", "incorrect", "avoided")


@lru_cache
def _catalogue() -> dict:
    with open(get_settings().grammar_skills_path, encoding="utf-8") as f:
        return json.load(f)


def groups() -> list[dict]:
    return _catalogue()["groups"]


def all_skills() -> list[dict]:
    """Umiejętności w kolejności wprowadzania."""
    return _catalogue()["skills"]


def skill_def(skill_id: str) -> dict | None:
    return _by_id().get(skill_id)


@lru_cache
def _by_id() -> dict[str, dict]:
    return {s["id"]: s for s in all_skills()}


def ensure_rows(db: Session) -> dict[str, GrammarSkill]:
    """Wiersz postępu dla każdej umiejętności z katalogu (katalog może rosnąć)."""
    rows = {r.skill_id: r for r in db.query(GrammarSkill).all()}
    missing = [s["id"] for s in all_skills() if s["id"] not in rows]
    for sid in missing:
        # wartości jawnie: domyślne z kolumn pojawiają się dopiero po flush
        row = GrammarSkill(
            skill_id=sid, level=NEW, streak=0, lapses=0, interval_idx=0,
            attempts=0, correct=0, wild_uses=0,
        )
        db.add(row)
        rows[sid] = row
    if missing:
        db.commit()
    return rows


def fast_threshold_ms(prompt: str, cue: str = "") -> int:
    """Granica "szybkiej" odpowiedzi. Nagrywanie rusza razem z pojawieniem się
    polecenia, więc czas reakcji zawiera czytanie - stąd dodatek za każde słowo."""
    words = len((prompt + " " + cue).split())
    return 2000 + 300 * words


def learning_fmt(skill: GrammarSkill) -> str:
    """Na poziomie LEARNING: najpierw z widocznym kształtem, potem sama sytuacja."""
    return "guided" if skill.streak < GUIDED_STREAK else "situation"


def is_due(skill: GrammarSkill, today: date) -> bool:
    return skill.level >= SOLID and skill.next_due is not None and skill.next_due <= today.isoformat()


def apply_answer(
    skill: GrammarSkill,
    verdict: str,
    *,
    hint_used: bool = False,
    fast: bool = False,
    today: date,
) -> tuple[int, int]:
    """Aktualizuje postęp po jednej ocenionej odpowiedzi. Zwraca (poziom przed, po).

    "avoided" (poprawne zdanie, które ominęło strukturę) liczy się jak błąd:
    niczego nie przećwiczono. "unclear" niczego nie zmienia.
    """
    before = skill.level
    if verdict not in GRADED:
        return before, before

    ok = verdict == "correct"
    due = is_due(skill, today)
    skill.attempts += 1
    skill.correct += 1 if ok else 0
    skill.last_seen = today.isoformat()
    skill.updated_at = now_iso()

    if skill.level == NEW:
        # pierwsze zetknięcie jest sondą bez pomocy: kto umie, nie przechodzi nauki
        if ok and not hint_used:
            skill.level, skill.streak = UNAIDED, 1
        else:
            skill.level, skill.streak = LEARNING, 0
        skill.lapses = 0

    elif skill.level == LEARNING:
        if ok:
            # poprawna odpowiedź po podejrzeniu podpowiedzi nie przybliża do awansu
            if not hint_used:
                skill.streak += 1
            if skill.streak >= LEARNING_STREAK:
                skill.level, skill.streak, skill.lapses = UNAIDED, 0, 0
        else:
            skill.streak = max(0, skill.streak - 1)

    elif skill.level == UNAIDED:
        if ok:
            skill.streak += 1
            skill.lapses = 0
            if (skill.streak >= SOLID_STREAK and fast) or skill.streak >= SOLID_STREAK_ANY_SPEED:
                skill.level, skill.streak, skill.interval_idx = SOLID, 0, 0
                skill.next_due = (today + timedelta(days=REVIEW_INTERVALS[0])).isoformat()
        else:
            skill.streak = 0
            skill.lapses += 1
            if skill.lapses >= LAPSES_TO_RELEARN:
                # GUIDED_STREAK: wraca od razu do sytuacji z podpowiedzią, nie do zera
                skill.level, skill.streak, skill.lapses = LEARNING, GUIDED_STREAK, 0

    elif skill.level == SOLID:
        if ok and due:
            skill.interval_idx += 1
            if skill.interval_idx >= len(REVIEW_INTERVALS):
                skill.level, skill.interval_idx = MASTERED, 0
                skill.next_due = (today + timedelta(days=MASTERED_INTERVALS[0])).isoformat()
            else:
                skill.next_due = (
                    today + timedelta(days=REVIEW_INTERVALS[skill.interval_idx])
                ).isoformat()
        elif not ok and due:
            # nie przetrwała przerwy: wraca do codziennego ćwiczenia
            skill.level, skill.streak, skill.lapses, skill.next_due = UNAIDED, 1, 0, None
        elif not ok:
            # błąd poza terminem powtórki: bez degradacji, ale sprawdzamy jutro od nowa
            skill.interval_idx = 0
            skill.next_due = (today + timedelta(days=1)).isoformat()

    elif skill.level == MASTERED:
        if ok and due:
            skill.interval_idx = min(skill.interval_idx + 1, len(MASTERED_INTERVALS) - 1)
            skill.next_due = (
                today + timedelta(days=MASTERED_INTERVALS[skill.interval_idx])
            ).isoformat()
        elif not ok:
            skill.level, skill.interval_idx = SOLID, 1
            skill.next_due = (today + timedelta(days=REVIEW_INTERVALS[0])).isoformat()

    return before, skill.level
