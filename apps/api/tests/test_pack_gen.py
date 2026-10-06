"""Testy walidatora generatora SourcePack (spec §7) - bez wywołań LLM."""

from app.services import llm
from app.services.pack_gen import unknown_words, validate_generated_pack

KNOWN = {
    "i", "go", "home", "yesterday", "and", "cook", "dinner", "for", "my",
    "family", "the", "kitchen", "be", "small", "but", "warm", "we", "eat",
    "at", "table", "talk", "about", "work",
}


def make_pack(**overrides) -> llm.GeneratedSourcePack:
    base = dict(
        seed_text="I go home and cook dinner for my family.",
        guiding_questions=["What did I do?"],
        keywords=["home", "dinner"],
        chunks=[
            llm.GeneratedChunk(text="go home", prompt_pl="wracasz do domu"),
            llm.GeneratedChunk(text="cook dinner", prompt_pl="gotujesz kolację"),
        ],
        transfer_prompt="What do you usually cook on weekends?",
        task_type="narrative",
        requires_personal_recall=False,
    )
    base.update(overrides)
    return llm.GeneratedSourcePack(**base)


def test_unknown_words_flags_out_of_vocabulary_content_word():
    text = "I go home and defenestrate the furniture"
    unknown = unknown_words(text, KNOWN)
    assert "defenestrate" in unknown
    assert "furniture" in unknown  # not in KNOWN either


def test_unknown_words_allows_proper_nouns_and_numbers():
    text = "I met Sarah at three o'clock"
    unknown = unknown_words(text, KNOWN)
    assert "sarah" not in unknown


def test_unknown_words_empty_for_fully_known_text():
    text = "I go home and cook dinner for my family"
    assert unknown_words(text, KNOWN) == []


def test_validate_accepts_clean_pack():
    pack = make_pack()
    reasons = validate_generated_pack(pack, KNOWN, support_ceiling=4)
    assert reasons == []


def test_validate_rejects_unknown_vocabulary():
    pack = make_pack(seed_text="I defenestrate the mahogany armoire")
    reasons = validate_generated_pack(pack, KNOWN, support_ceiling=4)
    assert any("nieznane słowa" in r for r in reasons)


def test_validate_rejects_personal_recall_transfer_prompt():
    pack = make_pack(requires_personal_recall=True)
    reasons = validate_generated_pack(pack, KNOWN, support_ceiling=4)
    assert any("przypomnienia sobie faktu" in r for r in reasons)


def test_validate_rejects_argumentative_at_high_support():
    pack = make_pack(task_type="argumentative")
    reasons = validate_generated_pack(pack, KNOWN, support_ceiling=2)
    assert any("task_type" in r for r in reasons)


def test_validate_allows_argumentative_at_low_support():
    pack = make_pack(task_type="argumentative")
    reasons = validate_generated_pack(pack, KNOWN, support_ceiling=1)
    assert reasons == []


def test_validate_rejects_missing_chunks_or_questions():
    pack = make_pack(chunks=[], guiding_questions=[])
    reasons = validate_generated_pack(pack, KNOWN, support_ceiling=4)
    assert any("chunks" in r for r in reasons)
    assert any("guiding_questions" in r for r in reasons)
