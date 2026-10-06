"""Silnik metryk - rdzeń systemu (spec sekcja 5).

Wszystkie metryki czasowe liczone z segmentów VAD (nie z timestampów Whispera).
Timestampy słów służą do przypisania słów do odcinków mowy i klasyfikacji pozycji pauz.
Oznaczenia: T = czas od t0 do końca nagrania, P = suma długości segmentów mowy,
W = liczba słów.
"""

import re
from dataclasses import dataclass

SILENT_PAUSE_S = 0.25
LONG_PAUSE_S = 1.0

# spójniki, po których pauza na początku zdania jest naturalna (granica, nie mid-clause)
BOUNDARY_CONJUNCTIONS = {
    "and", "but", "so", "because", "then", "also", "however", "although", "or",
}

SENTENCE_PUNCT = (".", "!", "?", ",", ";", ":")


@dataclass
class Pause:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def _internal_pauses(
    segments: list[tuple[float, float]], min_duration: float = SILENT_PAUSE_S
) -> list[Pause]:
    """Przerwy między kolejnymi segmentami mowy (wewnątrz wypowiedzi)."""
    pauses = []
    for (_, end_a), (start_b, _) in zip(segments, segments[1:]):
        if start_b - end_a >= min_duration:
            pauses.append(Pause(end_a, start_b))
    return pauses


def _classify_pause_positions(
    pauses: list[Pause],
    words: list[dict],
    clause_boundary_indices: set[int] | None = None,
) -> tuple[list[Pause], list[Pause]]:
    """Zwraca (mid_clause_pauses, boundary_pauses).

    Pauza jest boundary (nie mid-clause), jeśli występuje bezpośrednio po
    znaku interpunkcyjnym w transkrypcji, przed spójnikiem rozpoczynającym
    nowe zdanie, lub - gdy dostępna - przed słowem oznaczonym jako początek
    nowej klauzuli przez lang_metrics.clause_boundaries (spec 5.1).
    """
    if not words:
        return [], list(pauses)
    mid: list[Pause] = []
    boundary: list[Pause] = []
    for pause in pauses:
        before = [w for w in words if w["end"] <= pause.start + 0.15]
        after_idx = next(
            (i for i, w in enumerate(words) if w["start"] >= pause.end - 0.15), None
        )
        prev_word = before[-1]["word"].strip() if before else ""
        next_word = (
            words[after_idx]["word"].strip().lower() if after_idx is not None else ""
        )
        next_word = re.sub(r"[^a-z']", "", next_word)
        is_boundary = (
            prev_word.endswith(SENTENCE_PUNCT) or next_word in BOUNDARY_CONJUNCTIONS
        )
        if not is_boundary and clause_boundary_indices and after_idx in clause_boundary_indices:
            is_boundary = True
        (boundary if is_boundary else mid).append(pause)
    return mid, boundary


def _runs(words: list[dict], pauses: list[Pause]) -> list[int]:
    """Liczba słów w kolejnych odcinkach między pauzami >= 250 ms."""
    if not words:
        return []
    boundaries = sorted(p.start for p in pauses)
    runs: list[int] = []
    current = 0
    b_idx = 0
    for w in words:
        while b_idx < len(boundaries) and boundaries[b_idx] < w["start"]:
            b_idx += 1
            if current > 0:
                runs.append(current)
                current = 0
        current += 1
    if current > 0:
        runs.append(current)
    return runs


def count_fillers(transcript: str, fillers: list[str]) -> int:
    """Wypełniacze: jednowyrazowe po tokenach, wielowyrazowe po sekwencjach tokenów."""
    tokens = _tokenize(transcript)
    count = 0
    single = {f for f in fillers if " " not in f}
    multi = [f.split() for f in fillers if " " in f]
    count += sum(1 for t in tokens if t in single)
    for phrase in multi:
        n = len(phrase)
        count += sum(
            1 for i in range(len(tokens) - n + 1) if tokens[i : i + n] == phrase
        )
    return count


def compute_metrics(
    segments: list[tuple[float, float]],
    t0_s: float,
    recording_end_s: float,
    words: list[dict] | None,
    transcript: str | None,
    fillers: list[str] | None = None,
    clause_boundary_indices: set[int] | None = None,
    clause_segmentation_confidence: float = 0.0,
) -> dict:
    """Metryki per próba. segments i words w sekundach absolutnych nagrania."""
    words = words or []
    transcript = transcript or ""
    fillers = fillers or []

    # tylko mowa po bodźcu; segment zaczęty przed t0 przycinamy
    segs = [(max(s, t0_s), e) for s, e in segments if e > t0_s]

    T = max(recording_end_s - t0_s, 1e-6)
    P = sum(e - s for s, e in segs)
    W = len(words)

    pauses = _internal_pauses(segs)
    long_pauses = [p for p in pauses if p.duration >= LONG_PAUSE_S]
    mid_pauses, boundary_pauses = _classify_pause_positions(
        pauses, words, clause_boundary_indices
    )
    mid, boundary = len(mid_pauses), len(boundary_pauses)
    runs = _runs(words, pauses)

    ttfw = (segs[0][0] - t0_s) if segs else None
    speaking_minutes = max(T / 60.0, 1e-6)

    m: dict = {
        "ttfw": round(ttfw, 3) if ttfw is not None else None,
        "phonation_time_ratio": round(P / T, 3),
        "speech_rate": round(W / T * 60.0, 1) if W else None,
        "articulation_rate": round(W / P * 60.0, 1) if W and P > 0 else None,
        "mean_length_of_run": round(sum(runs) / len(runs), 2) if runs else None,
        "max_length_of_run": max(runs) if runs else None,
        "silent_pause_count": len(pauses),
        "long_pause_count": len(long_pauses),
        "mean_pause_duration": (
            round(sum(p.duration for p in pauses) / len(pauses), 3) if pauses else None
        ),
        "pause_position_ratio": (
            round(mid / len(pauses), 3) if pauses and words else None
        ),
        "mid_clause_pause_count": mid if words else None,
        "mid_clause_pause_rate": (
            round(mid / speaking_minutes, 2) if words else None
        ),
        "clause_segmentation_confidence": clause_segmentation_confidence,
        "mid_clause_pause_duration": (
            round(sum(p.duration for p in mid_pauses) / len(mid_pauses), 3)
            if mid_pauses
            else None
        ),
        "mid_clause_pause_frequency": (
            round(len(mid_pauses) / speaking_minutes, 2) if words else None
        ),
        "clause_final_pause_duration": (
            round(sum(p.duration for p in boundary_pauses) / len(boundary_pauses), 3)
            if boundary_pauses
            else None
        ),
        "clause_final_pause_frequency": (
            round(len(boundary_pauses) / speaking_minutes, 2) if words else None
        ),
        "longest_speech_segment_s": (
            round(max(e - s for s, e in segs), 2) if segs else None
        ),
        "word_count": W or None,
        "duration_from_t0_s": round(T, 2),
        "phonation_s": round(P, 2),
    }

    if transcript and W:
        filler_count = count_fillers(transcript, fillers)
        m["filler_count"] = filler_count
        m["filler_rate"] = round(filler_count / W * 100.0, 2)

    # przebieg fonacji w kostkach 5 s - do wykresu Fluency Sprint
    if T > 0:
        bins: list[float] = []
        bin_s = 5.0
        t = t0_s
        while t < recording_end_s:
            t_end = min(t + bin_s, recording_end_s)
            overlap = sum(
                max(0.0, min(e, t_end) - max(s, t)) for s, e in segs
            )
            bins.append(round(overlap / max(t_end - t, 1e-6), 3))
            t = t_end
        m["phonation_timeline"] = bins

    return m
