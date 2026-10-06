"""Bottleneck Diagnostic (spec zmian §2): sprawdza, czy największy koszt
spontanicznej wypowiedzi pojawia się przy generowaniu treści (conceptualization),
formulacji językowej, czy przy braku przygotowania - a nie ocenia jakości
odpowiedzi. Świadomie osobne od SpeakingSession: /api/stats/progress i Baseline
tego modułu w ogóle nie widzą.
"""

import logging
import statistics

from sqlalchemy.orm import Session

from ..models import (
    Attempt,
    DiagnosticSession,
    DiagnosticTrial,
    FluencyMetrics,
    Round,
    SpeakingSession,
)
from . import llm
from .constants import KEYWORD_PLAN_MAX_ITEMS, KEYWORD_PLAN_MAX_WORDS
from .pack_gen import _active_personal_context, known_lemma_set, unknown_words

logger = logging.getLogger(__name__)

MAX_GENERATION_ATTEMPTS = 3
SPEAK_LIMIT_S = 60
PLANNING_S = {
    "cold": 5,
    "supplied_ideas": 10,
    "self_plan": 30,
    "repetition": 5,
    "native_control": 5,
}
CONDITION_ORDER = ["cold", "supplied_ideas", "self_plan", "repetition", "native_control"]
MIN_SESSIONS_FOR_PROFILE = 3

# pola tekstowe po angielsku - walidowane wobec KnownVocabulary; native_control
# jest po polsku i celowo pomijane
_ENGLISH_FIELDS = ("cold", "supplied_ideas_prompt", "self_plan")


def _validate(result: llm.GeneratedDiagnosticPromptSet, known_lemmas: set[str]) -> list[str]:
    reasons: list[str] = []
    for field in _ENGLISH_FIELDS:
        unknown = unknown_words(getattr(result, field), known_lemmas)
        if unknown:
            reasons.append(f"nieznane słowa w {field}: {', '.join(unknown[:10])}")
    if len(result.supplied_ideas) != 3:
        reasons.append("supplied_ideas musi mieć dokładnie 3 elementy")
    if any(len(idea.split()) > 4 for idea in result.supplied_ideas):
        reasons.append("supplied_ideas: kierunki muszą być krótkie (max 4 słowa)")
    return reasons


def _generate_prompt_set(db: Session) -> llm.GeneratedDiagnosticPromptSet | None:
    if not llm.llm_enabled():
        return None
    known_lemmas = known_lemma_set(db)
    personal_context = _active_personal_context(db)
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        result = llm.complete_json(
            "diagnostic_prompt_set",
            {"personal_context": personal_context or "(brak zapisanego kontekstu)"},
            llm.GeneratedDiagnosticPromptSet,
        )
        if result is None:
            continue
        reasons = _validate(result, known_lemmas)
        if not reasons:
            return result
        logger.warning(
            "Diagnostic prompt set odrzucony (próba %d/%d): %s",
            attempt + 1, MAX_GENERATION_ATTEMPTS, "; ".join(reasons),
        )
    return None


def start_diagnostic_session(db: Session, language_control_enabled: bool) -> DiagnosticSession | None:
    result = _generate_prompt_set(db)
    if result is None:
        return None

    session = DiagnosticSession(language_control_enabled=language_control_enabled)
    db.add(session)
    db.flush()

    cold = DiagnosticTrial(
        diagnostic_session_id=session.id, condition="cold", prompt=result.cold,
        planning_seconds=PLANNING_S["cold"], speaking_limit_seconds=SPEAK_LIMIT_S, order_in_session=1,
    )
    supplied = DiagnosticTrial(
        diagnostic_session_id=session.id, condition="supplied_ideas", prompt=result.supplied_ideas_prompt,
        support_json={"ideas": result.supplied_ideas},
        planning_seconds=PLANNING_S["supplied_ideas"], speaking_limit_seconds=SPEAK_LIMIT_S, order_in_session=2,
    )
    self_plan = DiagnosticTrial(
        diagnostic_session_id=session.id, condition="self_plan", prompt=result.self_plan,
        planning_seconds=PLANNING_S["self_plan"], speaking_limit_seconds=SPEAK_LIMIT_S, order_in_session=3,
    )
    db.add_all([cold, supplied, self_plan])
    db.flush()

    repetition = DiagnosticTrial(
        diagnostic_session_id=session.id, condition="repetition", prompt=self_plan.prompt,
        source_trial_id=self_plan.id,
        planning_seconds=PLANNING_S["repetition"], speaking_limit_seconds=SPEAK_LIMIT_S, order_in_session=4,
    )
    db.add(repetition)

    if language_control_enabled:
        db.add(DiagnosticTrial(
            diagnostic_session_id=session.id, condition="native_control", prompt=result.native_control,
            planning_seconds=PLANNING_S["native_control"], speaking_limit_seconds=SPEAK_LIMIT_S, order_in_session=5,
        ))

    db.commit()
    return session


def submit_plan(db: Session, trial: DiagnosticTrial, items: list[str]) -> None:
    if not items or len(items) > KEYWORD_PLAN_MAX_ITEMS:
        raise ValueError(f"Maksymalnie {KEYWORD_PLAN_MAX_ITEMS} hasła")
    cleaned = [str(i).strip() for i in items]
    if any(not i for i in cleaned):
        raise ValueError("Puste hasło")
    if any(len(i.split()) > KEYWORD_PLAN_MAX_WORDS for i in cleaned):
        raise ValueError(f"Maksymalnie {KEYWORD_PLAN_MAX_WORDS} słów na hasło")
    trial.support_json = {"items": cleaned}


def _fm_for_trial(db: Session, trial: DiagnosticTrial) -> FluencyMetrics | None:
    if trial.attempt_id is None:
        return None
    return db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == trial.attempt_id).first()


def _by_condition(db: Session, session_id: int) -> dict[str, FluencyMetrics | None]:
    trials = db.query(DiagnosticTrial).filter(DiagnosticTrial.diagnostic_session_id == session_id).all()
    return {t.condition: _fm_for_trial(db, t) for t in trials}


# spec zmian §2.5: warstwa heurystyczna, neutralny język, nigdy "masz problem z X"
def session_note(db: Session, session: DiagnosticSession) -> list[str] | None:
    if session.status != "completed":
        return None
    fm = _by_condition(db, session.id)
    notes: list[str] = []

    def phon(cond: str) -> float | None:
        m = fm.get(cond)
        return m.phonation_time_ratio if m else None

    cold_p, supplied_p, self_p, rep_p = phon("cold"), phon("supplied_ideas"), phon("self_plan"), phon("repetition")

    if cold_p is not None and supplied_p is not None and self_p is not None:
        supported_avg = statistics.mean(v for v in (supplied_p, self_p) if v is not None)
        if supported_avg > cold_p * 1.15:
            notes.append(
                "Wsparcie w wyborze treści wyraźnie poprawia płynność. Największym "
                "kosztem może być szybkie generowanie i porządkowanie pomysłów."
            )
    if cold_p is not None and self_p is not None and self_p > cold_p * 1.1:
        notes.append(
            "Krótki plan przed wypowiedzią znacząco pomaga. Warto trenować "
            "stopniowe skracanie czasu planowania."
        )
    if self_p is not None and rep_p is not None and rep_p > self_p * 1.1:
        notes.append(
            "Powtórzenie mocno zmniejsza koszt produkcji wypowiedzi. Trening "
            "powtarzania tego samego zadania jest prawdopodobnie szczególnie użyteczny."
        )

    native_fm = fm.get("native_control")
    if native_fm and native_fm.phonation_time_ratio is not None and cold_p is not None:
        if abs(native_fm.phonation_time_ratio - cold_p) < 0.1:
            notes.append(
                "Podobny wzorzec pojawił się również w próbie po polsku. Część "
                "trudności może pojawiać się jeszcze przed wyborem angielskich "
                "słów - podczas budowania i utrzymywania planu wypowiedzi."
            )

    completed = (
        db.query(DiagnosticSession).filter(DiagnosticSession.status == "completed").count()
    )
    if completed < MIN_SESSIONS_FOR_PROFILE:
        notes.append("Profil staje się bardziej wiarygodny po minimum 3 sesjach diagnostycznych.")

    return notes


def _label(ratio: float | None, high: float, low: float) -> str:
    if ratio is None:
        return "unclear"
    if ratio >= high:
        return "high"
    if ratio <= low:
        return "low"
    return "medium"


def bottleneck_profile(db: Session) -> dict | None:
    """spec zmian §15: profil opisowy po >=3 ukończonych sesjach diagnostycznych,
    wyłącznie etykiety high/medium/low + disclaimer, nigdy procentowe diagnozy."""
    completed_sessions = (
        db.query(DiagnosticSession).filter(DiagnosticSession.status == "completed").all()
    )
    if len(completed_sessions) < MIN_SESSIONS_FOR_PROFILE:
        return None

    per_condition: dict[str, list[float]] = {c: [] for c in CONDITION_ORDER}
    for session in completed_sessions:
        for condition, fm in _by_condition(db, session.id).items():
            if fm and fm.phonation_time_ratio is not None:
                per_condition.setdefault(condition, []).append(fm.phonation_time_ratio)

    def med(cond: str) -> float | None:
        vals = per_condition.get(cond) or []
        return statistics.median(vals) if vals else None

    cold, supplied, self_plan, repetition, native = (
        med("cold"), med("supplied_ideas"), med("self_plan"), med("repetition"), med("native_control")
    )

    def ratio(a: float | None, b: float | None) -> float | None:
        return (a / b) if (a is not None and b is not None and b > 0) else None

    supported_avg = (
        statistics.mean(v for v in (supplied, self_plan) if v is not None)
        if supplied is not None or self_plan is not None
        else None
    )

    profile = {
        "content_generation_sensitivity": _label(ratio(supported_avg, cold), 1.15, 1.03),
        "planning_benefit": _label(ratio(self_plan, cold), 1.10, 1.02),
        "repetition_benefit": _label(ratio(repetition, self_plan), 1.10, 1.02),
        "l2_specific_cost": (
            "unclear" if native is None or cold is None
            else ("low" if abs(native - cold) < 0.1 else "high")
        ),
        "sustained_speech_cost": _sustained_speech_cost(db),
        "disclaimer": (
            "To profil treningowy oparty na wzorcach w Twoich próbach, nie "
            "diagnoza medyczna ani psychologiczna."
        ),
    }
    return profile


def _sustained_speech_cost(db: Session) -> str:
    """Trend jakości w kolejnych rundach zwykłych sesji (Runda 1 vs Runda 4,
    phonation_time_ratio) z ostatnich ukończonych SpeakingSession - bez nowej
    tabeli, reużywa dane już zbierane przez sesje mówienia."""
    sessions = (
        db.query(SpeakingSession)
        .filter(SpeakingSession.ended_at.isnot(None))
        .order_by(SpeakingSession.id.desc())
        .limit(10)
        .all()
    )
    r1_vals, r4_vals = [], []
    for s in sessions:
        for number, bucket in ((1, r1_vals), (4, r4_vals)):
            r = db.query(Round).filter(Round.session_id == s.id, Round.number == number).first()
            if r is None:
                continue
            a = (
                db.query(Attempt)
                .filter(Attempt.round_id == r.id, Attempt.status == "done")
                .order_by(Attempt.id.desc())
                .first()
            )
            if a is None:
                continue
            fm = db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == a.id).first()
            if fm and fm.phonation_time_ratio is not None:
                bucket.append(fm.phonation_time_ratio)
    if not r1_vals or not r4_vals:
        return "unclear"
    r4_over_r1 = statistics.median(r4_vals) / statistics.median(r1_vals) if statistics.median(r1_vals) > 0 else None
    if r4_over_r1 is None:
        return "unclear"
    # niski r4/r1 = duży spadek fonacji w toku sesji = wysoki koszt (odwrotnie
    # niż w _label, gdzie wysoki stosunek oznacza wysoką korzyść/wrażliwość)
    if r4_over_r1 <= 0.85:
        return "high"
    if r4_over_r1 >= 0.97:
        return "low"
    return "medium"
