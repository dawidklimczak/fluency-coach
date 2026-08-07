"""Trener tempa czytania: dopasowanie wzorca do wypowiedzi i tempo lokalne."""

import pytest

from app.services.reading import (
    STATUS_MISSED,
    STATUS_SPOKEN,
    STATUS_UNCLEAR,
    align,
    compute,
    local_speeds,
    normalize,
    tokenize_reference,
)


def spoken(words):
    """[(słowo, start, end)] -> format z Whispera."""
    return [{"word": w, "start": s, "end": e} for w, s, e in words]


def even_reading(text: str, wpm: float, start: float = 0.0):
    """Nagranie idealnie równe: każde słowo trwa tyle samo."""
    per_word = 60.0 / wpm
    out = []
    t = start
    for word in text.split():
        out.append({"word": word, "start": t, "end": t + per_word * 0.8})
        t += per_word
    return out


def test_normalize_strips_punctuation_keeps_apostrophes():
    assert normalize("Don't,") == "don't"
    assert normalize("HELLO!") == "hello"
    assert normalize("—") == ""


def test_tokenize_marks_line_starts():
    tokens = tokenize_reference("first line\nsecond line")
    assert [t["text"] for t in tokens] == ["first", "line", "second", "line"]
    assert tokens[2]["newline_before"] is True
    assert tokens[0]["newline_before"] is False


def test_perfect_reading_all_spoken():
    text = "the quick brown fox"
    aligned, extra = align(tokenize_reference(text), even_reading(text, 120))
    assert [t["status"] for t in aligned] == [STATUS_SPOKEN] * 4
    assert extra == 0
    assert aligned[0]["start"] == pytest.approx(0.0)


def test_skipped_word_is_missed():
    reference = tokenize_reference("the quick brown fox jumps")
    aligned, _ = align(reference, even_reading("the quick fox jumps", 120))
    statuses = {t["text"]: t["status"] for t in aligned}
    assert statuses["brown"] == STATUS_MISSED
    assert statuses["quick"] == STATUS_SPOKEN
    # pominięte słowo nie dostaje czasu
    assert next(t for t in aligned if t["text"] == "brown")["start"] is None


def test_misread_word_is_unclear_and_keeps_what_was_heard():
    reference = tokenize_reference("the quick brown fox")
    aligned, _ = align(reference, spoken([
        ("the", 0.0, 0.2), ("quick", 0.3, 0.6),
        ("brownie", 0.7, 1.1), ("fox", 1.2, 1.5),
    ]))
    brown = next(t for t in aligned if t["text"] == "brown")
    assert brown["status"] == STATUS_UNCLEAR
    assert brown["heard"] == "brownie"


def test_replace_shorter_than_reference_marks_rest_as_missed():
    """Gdy padło mniej słów niż jest we wzorcu, nadmiar to pominięcie,
    a nie 'niewyraźnie' - nic tam nie zabrzmiało."""
    reference = tokenize_reference("alpha bravo charlie delta")
    aligned, _ = align(reference, spoken([("zulu", 0.0, 0.4)]))
    statuses = [t["status"] for t in aligned]
    assert statuses[0] == STATUS_UNCLEAR
    assert statuses[1:] == [STATUS_MISSED] * 3
    assert all(t["start"] is None for t in aligned[1:])


def test_extra_words_counted():
    reference = tokenize_reference("the quick fox")
    aligned, extra = align(reference, even_reading("the quick um the quick fox", 120))
    assert extra > 0
    assert all(t["status"] != STATUS_MISSED for t in aligned)


def test_punctuation_does_not_break_matching():
    reference = tokenize_reference("Hello, world! It's fine.")
    aligned, _ = align(reference, even_reading("hello world its fine", 120))
    # "it's" vs "its" różni się apostrofem - dopasowanie ma to znieść jako
    # niepewność, a nie wywrócić reszty tekstu
    assert [t["status"] for t in aligned][:2] == [STATUS_SPOKEN, STATUS_SPOKEN]
    assert aligned[3]["status"] == STATUS_SPOKEN


def test_local_speed_tracks_tempo_change():
    # pierwsza połowa wolno (60 wpm), druga szybko (180 wpm)
    slow = even_reading("one two three four five six", 60)
    fast = even_reading("seven eight nine ten eleven twelve", 180, start=slow[-1]["end"] + 0.1)
    reference = tokenize_reference(
        "one two three four five six seven eight nine ten eleven twelve"
    )
    aligned, _ = align(reference, slow + fast)
    local_speeds(aligned)

    assert aligned[1]["wpm"] < 100
    assert aligned[-2]["wpm"] > 140


def test_compute_overall_metrics():
    text = "the quick brown fox jumps over the lazy dog"
    words = even_reading(text, 120)
    duration = words[-1]["end"] + 0.2
    aligned, metrics = compute(
        reference_text=text,
        spoken_words=words,
        transcript=text,
        duration_s=duration,
        phonation_s=duration * 0.9,
        target_wpm=130,
    )
    assert metrics["words_read"] == 9
    assert metrics["missed_count"] == 0
    assert metrics["accuracy"] == 1.0
    assert metrics["wpm"] == pytest.approx(120, abs=15)
    assert metrics["wpm_articulation"] > metrics["wpm"]
    assert metrics["wpm_vs_target"] < 0  # wolniej niż cel 130
    assert len(aligned) == 9


def test_compute_flags_pauses():
    words = even_reading("one two three", 120)
    # sztuczna przerwa 1 s przed ostatnim słowem
    words[2]["start"] += 1.0
    words[2]["end"] += 1.0
    _, metrics = compute(
        reference_text="one two three",
        spoken_words=words,
        transcript="one two three",
        duration_s=words[-1]["end"],
        phonation_s=1.0,
        target_wpm=130,
    )
    assert metrics["pause_count"] == 1
    assert metrics["longest_pauses"][0]["before"] == "three"


def test_structures_route_not_swallowed_by_id_route():
    """/api/reading/structures musi trafiać do listy struktur, a nie być
    czytane jako identyfikator próby."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        res = c.get("/api/reading/structures")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 21
        assert {"id", "label"} <= set(items[0])


def test_generate_validates_input():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        # nieznana struktura
        r = c.post(
            "/api/reading/generate",
            json={"minutes": 2, "structures": ["nie_ma_takiej"]},
        )
        assert r.status_code in (404, 503)
        # czas poza zakresem
        r2 = c.post("/api/reading/generate", json={"minutes": 99})
        assert r2.status_code == 422


def test_compute_without_transcript_does_not_crash():
    _, metrics = compute(
        reference_text="some text here",
        spoken_words=[],
        transcript="",
        duration_s=5.0,
        phonation_s=3.0,
        target_wpm=130,
    )
    assert metrics["transcript_missing"] is True
    assert metrics["words_read"] == 0
    assert metrics["missed_count"] == 3
