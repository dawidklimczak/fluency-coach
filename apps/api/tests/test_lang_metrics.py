"""Testy metryk językowych 5.2 (syntetyczne transkrypcje, bez API)."""

import pytest

from app.services.lang_metrics import (
    clause_boundaries,
    compute_language_metrics,
    lexical_distance,
    mtld,
)


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_direct_repetition_counted_as_repetition_and_repair():
    m = compute_language_metrics("I was I was thinking about it", None)
    assert m["repetition_count"] == 1
    assert m["repair_count"] >= 1


def test_distant_ngram_repair_not_repetition():
    # "go there" powtórzone w odległości 3 słów - autokorekta, nie repetycja
    m = compute_language_metrics("go there no wait first go there", None)
    assert m["repetition_count"] == 0
    assert m["repair_count"] >= 1


def test_repair_marker():
    m = compute_language_metrics(
        "it was great I mean it was fine", None, ["i mean", "no wait"]
    )
    assert m["repair_count"] >= 1


def test_false_start_detection():
    words = [
        w("I", 0.0, 0.2), w("went", 0.2, 0.5),
        # pauza 0.5 s, wznowienie innym słowem funkcyjnym
        w("we", 1.0, 1.2), w("took", 1.2, 1.5), w("the", 1.5, 1.6), w("train", 1.6, 2.0),
    ]
    m = compute_language_metrics("I went we took the train", words)
    assert m["false_start_count"] == 1


def test_no_false_start_after_sentence_end():
    words = [
        w("done.", 0.0, 0.4),
        w("we", 1.0, 1.2), w("left", 1.2, 1.5),
    ]
    m = compute_language_metrics("done. we left", words)
    assert m["false_start_count"] == 0


def test_mtld_higher_for_diverse_text():
    repetitive = ("the cat sat on the mat " * 10).split()
    diverse = (
        "quantum archives bloom under crimson skies while distant travelers "
        "gather ancient maps describing forgotten harbors near volcanic islands "
        "whose keepers trade silver instruments for woven baskets full of amber"
    ).split()
    assert mtld(diverse) > mtld(repetitive)


def test_subordination_and_mlu():
    m = compute_language_metrics(
        "I stayed home because it was raining. The dog slept.", None
    )
    assert m["sentence_count"] == 2
    assert m["subordination_index"] == pytest.approx(0.5)
    assert m["mean_length_utterance"] == pytest.approx(5.0)


def test_word_frequency_profile_rare_words():
    common = compute_language_metrics("I want to go home and see my friends now", None)
    rare = compute_language_metrics(
        "the ubiquitous xylophone resonated near the mausoleum entrance", None
    )
    assert rare["word_frequency_profile"] > common["word_frequency_profile"]


def test_lexical_distance_paraphrase():
    same = lexical_distance(
        "The meeting was moved to Friday", "The meeting was moved to Friday"
    )
    different = lexical_distance(
        "The meeting was moved to Friday",
        "Our discussion got rescheduled for the end of the week",
    )
    assert same == pytest.approx(0.0)
    assert different > 0.5


def test_empty_transcript():
    assert compute_language_metrics("", None) == {}


def test_clause_boundaries_at_sentence_starts():
    transcript = "This is a plan. We will start tomorrow."
    words = [w(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate(transcript.split())]
    idx, confidence = clause_boundaries(transcript, words)
    assert confidence == 1.0
    assert 0 in idx  # "This"
    assert 4 in idx  # "We"


def test_clause_boundaries_at_subordinate_clause():
    transcript = "I stayed home because it was raining"
    words = [w(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate(transcript.split())]
    idx, confidence = clause_boundaries(transcript, words)
    assert confidence == 1.0
    assert 3 in idx  # "because"


def test_clause_boundaries_at_coordinated_clause():
    transcript = "I like coffee but she likes tea"
    words = [w(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate(transcript.split())]
    idx, confidence = clause_boundaries(transcript, words)
    assert confidence == 1.0
    assert 3 in idx  # "but"


def test_clause_boundaries_empty_without_words():
    idx, confidence = clause_boundaries("I stayed home", None)
    assert idx == set()
    assert confidence == 0.0
