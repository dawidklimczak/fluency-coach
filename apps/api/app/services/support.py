"""System wsparcia i jego zdejmowanie (spec §4).

Kalibracja: pierwsze CALIBRATION_SESSIONS sesje na poziomie DEFAULT_CEILING,
bez zmian. Potem reguły zejścia/powrotu, obie liczone na ostatnich ukończonych
sesjach. Baseline to mediana krocząca (okno BASELINE_WINDOW) sond transferowych,
answered i redirected traktowane identycznie (dodatek v2B) - stalled włącza się
tylko przez to, że jego metryki po prostu wchodzą do puli jak każde inne.

Baseline per probe_type (spec zmian §6.5): far jest głównym sygnałem dla reguł
degradacji/awansu poniżej, near ma osobny baseline tylko do prezentacji
(Progress, podsumowanie sesji). Stara tabela Baseline jest zamrożona (patrz
models.py) - ten moduł czyta/pisze wyłącznie TransferBaseline.
"""

import statistics

from sqlalchemy.orm import Session

from ..models import Attempt, FluencyMetrics, Round, SpeakingSession, SupportEvent, TransferBaseline, TransferProbe

CALIBRATION_SESSIONS = 3
DEFAULT_CEILING = 4
MIN_CEILING = 0
MAX_CEILING = 4

DEMOTION_LOOKBACK = 4
DEMOTION_NEEDED = 3
DEMOTION_PAUSE_FACTOR = 0.85
DEMOTION_MLR_FACTOR = 0.8

PROMOTION_LOOKBACK = 2
PROMOTION_PHONATION_FACTOR = 0.7
PROMOTION_TIME_UTILIZATION = 0.6

BASELINE_WINDOW = 10
BASELINE_METRICS = ("mid_clause_pause_duration", "mean_length_of_run", "phonation_time_ratio")


def get_current_ceiling(db: Session) -> int:
    completed = db.query(SpeakingSession).filter(SpeakingSession.ended_at.isnot(None)).count()
    if completed < CALIBRATION_SESSIONS:
        return DEFAULT_CEILING
    latest = db.query(SupportEvent).order_by(SupportEvent.id.desc()).first()
    return latest.to_level if latest else DEFAULT_CEILING


def get_baseline_median(db: Session, metric_name: str, probe_type: str = "far") -> float | None:
    row = (
        db.query(TransferBaseline)
        .filter(TransferBaseline.metric_name == metric_name, TransferBaseline.probe_type == probe_type)
        .first()
    )
    return row.median if row else None


def push_baseline_value(
    db: Session, metric_name: str, value: float | None, probe_type: str = "far"
) -> None:
    if value is None:
        return
    from ..models import now_iso

    row = (
        db.query(TransferBaseline)
        .filter(TransferBaseline.metric_name == metric_name, TransferBaseline.probe_type == probe_type)
        .first()
    )
    if row is None:
        row = TransferBaseline(metric_name=metric_name, probe_type=probe_type, recent_values=[])
        db.add(row)
    values = list(row.recent_values or [])
    values.append(value)
    values = values[-BASELINE_WINDOW:]
    row.recent_values = values
    row.median = round(statistics.median(values), 4)
    row.updated_at = now_iso()


def update_baseline_from_transfer_probe(db: Session, probe: TransferProbe) -> None:
    """Pushuje metryki sondy do jej własnego (near/far) baseline'u. Sondy
    'legacy' (sprzed rozdziału near/far) nigdy tu nie trafiają - migracja ich
    nie klasyfikuje, więc nie mieszamy starych danych z nowymi seriami."""
    if probe.attempt_id is None or probe.probe_type not in ("near", "far"):
        return
    fm = db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == probe.attempt_id).first()
    if fm is None:
        return
    for key in BASELINE_METRICS:
        push_baseline_value(db, key, getattr(fm, key), probe.probe_type)
    db.commit()


def _transfer_probe_metrics(db: Session, session_id: int) -> FluencyMetrics | None:
    """Metryki sondy 'far' tej sesji - far jest głównym sygnałem dla reguł
    wsparcia (spec zmian §12); near liczy się tylko do prezentacji."""
    probe = (
        db.query(TransferProbe)
        .filter(TransferProbe.session_id == session_id, TransferProbe.probe_type == "far")
        .first()
    )
    if probe is None or probe.attempt_id is None:
        return None
    return db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == probe.attempt_id).first()


def _round_attempt_metrics(db: Session, session_id: int, round_number: int) -> FluencyMetrics | None:
    r = (
        db.query(Round)
        .filter(Round.session_id == session_id, Round.number == round_number)
        .first()
    )
    if r is None:
        return None
    attempt = (
        db.query(Attempt)
        .filter(Attempt.round_id == r.id, Attempt.status == "done")
        .order_by(Attempt.id.desc())
        .first()
    )
    if attempt is None:
        return None
    return db.query(FluencyMetrics).filter(FluencyMetrics.attempt_id == attempt.id).first()


def _demotion_criteria_met(db: Session, session_id: int, baseline_mid_clause: float | None) -> bool | None:
    probe_fm = _transfer_probe_metrics(db, session_id)
    r4_fm = _round_attempt_metrics(db, session_id, 4)
    if probe_fm is None or r4_fm is None:
        return None
    if probe_fm.mid_clause_pause_duration is None or probe_fm.mean_length_of_run is None:
        return None
    if not r4_fm.mean_length_of_run:
        return None
    cond1 = (
        baseline_mid_clause is not None
        and probe_fm.mid_clause_pause_duration <= baseline_mid_clause * DEMOTION_PAUSE_FACTOR
    )
    cond2 = probe_fm.mean_length_of_run >= DEMOTION_MLR_FACTOR * r4_fm.mean_length_of_run
    return bool(cond1 and cond2)


def _time_utilization(db: Session, session_id: int) -> float | None:
    rounds = db.query(Round).filter(Round.session_id == session_id).all()
    used = 0.0
    available = 0.0
    for r in rounds:
        attempt = (
            db.query(Attempt)
            .filter(Attempt.round_id == r.id, Attempt.status == "done")
            .order_by(Attempt.id.desc())
            .first()
        )
        available += r.speak_limit_s
        if attempt and attempt.duration_s:
            used += min(attempt.duration_s, r.speak_limit_s)
    if available <= 0:
        return None
    return used / available


def _promotion_criteria_met(db: Session, session_id: int, baseline_phonation: float | None) -> bool | None:
    probe_fm = _transfer_probe_metrics(db, session_id)
    if probe_fm is None or probe_fm.phonation_time_ratio is None:
        return None
    low_phonation = (
        baseline_phonation is not None
        and probe_fm.phonation_time_ratio < baseline_phonation * PROMOTION_PHONATION_FACTOR
    )
    utilization = _time_utilization(db, session_id)
    low_utilization = utilization is not None and utilization < PROMOTION_TIME_UTILIZATION
    return bool(low_phonation or low_utilization)


def evaluate_and_apply(db: Session, session: SpeakingSession) -> SupportEvent | None:
    """Wywoływane po zamknięciu sesji. Zwraca SupportEvent jeśli poziom się zmienił."""
    completed = (
        db.query(SpeakingSession)
        .filter(SpeakingSession.ended_at.isnot(None))
        .order_by(SpeakingSession.id.desc())
        .all()
    )
    if len(completed) < CALIBRATION_SESSIONS:
        return None

    ceiling = get_current_ceiling(db)
    baseline_mid = get_baseline_median(db, "mid_clause_pause_duration")
    baseline_phon = get_baseline_median(db, "phonation_time_ratio")

    last4 = completed[:DEMOTION_LOOKBACK]
    demotion_flags = [
        f for f in (_demotion_criteria_met(db, s.id, baseline_mid) for s in last4) if f is not None
    ]
    if (
        len(demotion_flags) >= DEMOTION_LOOKBACK
        and sum(demotion_flags) >= DEMOTION_NEEDED
        and ceiling > MIN_CEILING
    ):
        new_level = ceiling - 1
        event = SupportEvent(
            session_id=session.id,
            from_level=ceiling,
            to_level=new_level,
            direction="down",
            reason=(
                f"{sum(demotion_flags)}/{len(demotion_flags)} ostatnich sesji: "
                f"pauzy śródfrazowe <= {DEMOTION_PAUSE_FACTOR}x baseline "
                f"({baseline_mid}) i MLR sondy >= {DEMOTION_MLR_FACTOR}x MLR R4"
            ),
        )
        db.add(event)
        db.commit()
        return event

    last2 = completed[:PROMOTION_LOOKBACK]
    promotion_flags = [
        f for f in (_promotion_criteria_met(db, s.id, baseline_phon) for s in last2) if f is not None
    ]
    if (
        len(promotion_flags) >= PROMOTION_LOOKBACK
        and all(promotion_flags)
        and ceiling < MAX_CEILING
    ):
        new_level = ceiling + 1
        event = SupportEvent(
            session_id=session.id,
            from_level=ceiling,
            to_level=new_level,
            direction="up",
            reason=(
                f"{PROMOTION_LOOKBACK}/{PROMOTION_LOOKBACK} ostatnich sesji: "
                f"phonation_time_ratio sondy < {PROMOTION_PHONATION_FACTOR}x baseline "
                f"({baseline_phon}) lub wykorzystanie czasu < {PROMOTION_TIME_UTILIZATION * 100:.0f}%"
            ),
        )
        db.add(event)
        db.commit()
        return event

    return None


def should_interrupt_session(db: Session, session_id: int) -> bool:
    """Spec §4: przerwij, gdy phonation_time_ratio w R3 < 0.6 x wartość z R1."""
    r1_fm = _round_attempt_metrics(db, session_id, 1)
    r3_fm = _round_attempt_metrics(db, session_id, 3)
    if r1_fm is None or r3_fm is None:
        return False
    if r1_fm.phonation_time_ratio is None or r3_fm.phonation_time_ratio is None:
        return False
    return r3_fm.phonation_time_ratio < 0.6 * r1_fm.phonation_time_ratio
