"""Testy jednostkowe silnika metryk (bez audio - segmenty i słowa syntetyczne)."""

import pytest

from app.services.forbidden import find_forbidden
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


def test_forbidden_word_inflections():
    hits = find_forbidden("there was heavy raining outside", ["rain", "umbrella"])
    assert hits == ["rain"]
    assert find_forbidden("it keeps the water away", ["rain"]) == []


def test_forbidden_phrase():
    assert find_forbidden("stuck in a traffic jam", ["traffic jam"]) == ["traffic jam"]


def test_hallucination_filter_drops_words_outside_speech():
    from app.services.pipeline import filter_hallucinated_words

    segments = [(1.0, 3.0)]
    words = [
        w("real", 1.2, 1.5),
        w("also", 2.9, 3.2),        # lekko wystaje - tolerancja ma to zachować
        w("hallucinated", 6.0, 6.4),  # daleko poza mową
        w("it's", 8.0, 8.2),
    ]
    kept = filter_hallucinated_words(words, segments)
    assert [x["word"] for x in kept] == ["real", "also"]


def test_hallucination_filter_empty_segments_drops_all():
    from app.services.pipeline import filter_hallucinated_words

    words = [w("i", 0.5, 0.6), w("don't", 0.6, 0.8), w("know", 0.8, 1.0)]
    assert filter_hallucinated_words(words, []) == []


def test_no_speech_at_all():
    m = compute_metrics([], 0.0, 10.0, None, None)
    assert m["ttfw"] is None
    assert m["phonation_time_ratio"] == 0.0
