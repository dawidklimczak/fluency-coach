"""Testy jednostkowe silnika metryk (bez audio - segmenty i słowa syntetyczne)."""

import pytest

from app.services.metrics import compute_metrics, count_fillers


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_basic_timing_metrics():
    segments = [(1.0, 3.0), (3.5, 5.5), (7.0, 9.0)]
    m = compute_metrics(segments, t0_s=0.0, recording_end_s=10.0, words=None, transcript=None)

    assert m["ttfw"] == pytest.approx(1.0)
    assert m["phonation_s"] == pytest.approx(6.0)
    assert m["phonation_time_ratio"] == pytest.approx(0.6)
    assert m["silent_pause_count"] == 2  # 0.5 s i 1.5 s
    assert m["long_pause_count"] == 1   # 1.5 s
    assert m["mean_pause_duration"] == pytest.approx(1.0)
    assert m["longest_speech_segment_s"] == pytest.approx(2.0)


def test_t0_offset_shifts_ttfw():
    segments = [(2.5, 4.0)]
    m = compute_metrics(segments, t0_s=1.0, recording_end_s=5.0, words=None, transcript=None)
    assert m["ttfw"] == pytest.approx(1.5)
    assert m["duration_from_t0_s"] == pytest.approx(4.0)


def test_mean_length_of_run():
    # 4 słowa, pauza 0.6 s, 2 słowa
    segments = [(0.0, 2.0), (2.6, 4.0)]
    words = [
        w("I", 0.0, 0.3), w("think", 0.3, 0.7), w("this", 0.7, 1.0), w("works", 1.0, 1.9),
        w("really", 2.6, 3.0), w("well", 3.0, 3.4),
    ]
    m = compute_metrics(segments, 0.0, 4.0, words, "I think this works really well")
    assert m["mean_length_of_run"] == pytest.approx(3.0)
    assert m["max_length_of_run"] == 4


def test_pause_position_classification():
    # pauza po kropce = granica; pauza w środku frazy = mid-clause
    segments = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0)]
    words = [
        w("done.", 0.5, 1.0),
        w("next", 1.5, 1.9), w("thing", 1.9, 2.5),
        w("here", 3.0, 3.5),
    ]
    m = compute_metrics(segments, 0.0, 4.0, words, "done. next thing here")
    assert m["silent_pause_count"] == 2
    assert m["mid_clause_pause_count"] == 1
    assert m["pause_position_ratio"] == pytest.approx(0.5)


def test_filler_counting():
    text = "um so I was uh thinking you know that I mean it works"
    fillers = ["um", "uh", "you know", "i mean", "like"]
    assert count_fillers(text, fillers) == 4


def test_no_speech_at_all():
    m = compute_metrics([], 0.0, 10.0, None, None)
    assert m["ttfw"] is None
    assert m["phonation_time_ratio"] == 0.0


def test_clause_final_pause_duration_and_confidence_default_to_zero():
    # bez clause_boundary_indices: klasyfikacja tylko po interpunkcji/spójnikach
    segments = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0)]
    words = [
        w("done.", 0.5, 1.0),
        w("next", 1.5, 1.9), w("thing", 1.9, 2.5),
        w("here", 3.0, 3.5),
    ]
    m = compute_metrics(segments, 0.0, 4.0, words, "done. next thing here")
    assert m["clause_segmentation_confidence"] == 0.0
    assert m["mid_clause_pause_count"] == 1
    assert m["clause_final_pause_duration"] == pytest.approx(0.5)
    assert m["mid_clause_pause_duration"] == pytest.approx(0.5)


def test_clause_boundary_indices_reclassify_pause_as_boundary():
    # pauza przed spójnikiem podrzędnym "because" (bez interpunkcji przed nim)
    # jest mid-clause wg starej heurystyki, ale boundary wg indeksów klauzul
    segments = [(0.0, 1.0), (1.6, 2.5)]
    words = [
        w("I", 0.0, 0.3), w("stayed", 0.3, 1.0),
        w("because", 1.6, 2.0), w("rain", 2.0, 2.5),
    ]
    transcript = "I stayed because rain"
    m_default = compute_metrics(segments, 0.0, 2.5, words, transcript)
    assert m_default["mid_clause_pause_count"] == 0  # "because" already boundary conj

    # słowo bez oznaczenia jako spójnik graniczny, ale mimo to start klauzuli
    words2 = [
        w("I", 0.0, 0.3), w("stayed", 0.3, 1.0),
        w("since", 1.6, 2.0), w("it", 2.0, 2.5),
    ]
    m_no_idx = compute_metrics(segments, 0.0, 2.5, words2, "I stayed since it")
    assert m_no_idx["mid_clause_pause_count"] == 1

    m_with_idx = compute_metrics(
        segments, 0.0, 2.5, words2, "I stayed since it",
        clause_boundary_indices={2},
        clause_segmentation_confidence=1.0,
    )
    assert m_with_idx["mid_clause_pause_count"] == 0
    assert m_with_idx["clause_final_pause_duration"] == pytest.approx(0.6)
    assert m_with_idx["clause_segmentation_confidence"] == 1.0
