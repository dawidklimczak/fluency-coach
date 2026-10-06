"""Metryki językowe z transkrypcji (spec 5.2).

filler_rate liczony jest w metrics.py (nie wymaga NLP). Tutaj: autokorekty,
powtórzenia, MTLD, długość zdania, subordinacja i profil frekwencyjny.
Wszystko degraduje się do None, gdy spaCy/wordfreq są niedostępne -
metryki czasowe nigdy nie zależą od tego modułu.
"""

import re
from functools import lru_cache

from .nlp import get_nlp

FALSE_START_PAUSE_S = 0.3
MTLD_TTR_THRESHOLD = 0.72
TOP_N_FREQUENT = 2000

# spójniki podrzędne i klauzule podrzędne (dep_ spaCy) - granica AS-unit (spec 5)
SUBORDINATE_DEPS = {"advcl", "ccomp", "acl", "relcl", "csubj", "csubjpass"}

# słowa funkcyjne do detekcji fałszywych startów i dystansu leksykalnego
FUNCTION_POS = {"ADP", "AUX", "CCONJ", "DET", "PART", "PRON", "SCONJ", "PUNCT", "INTJ"}
FUNCTION_WORDS = {
    "i", "you", "he", "she", "it", "we", "they", "the", "a", "an", "and", "but",
    "or", "so", "if", "that", "this", "these", "those", "to", "of", "in", "on",
    "at", "for", "with", "is", "are", "was", "were", "be", "been", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "my", "your",
    "his", "her", "its", "our", "their", "there", "here", "what", "when", "who",
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


@lru_cache
def _top_frequent_words() -> set[str] | None:
    try:
        from wordfreq import top_n_list

        return set(top_n_list("en", TOP_N_FREQUENT))
    except Exception:
        return None


def mtld(tokens: list[str], threshold: float = MTLD_TTR_THRESHOLD) -> float | None:
    """Measure of Textual Lexical Diversity (McCarthy & Jarvis 2010).

    Średnia z przebiegu w przód i wstecz. Wymaga sensownej długości próbki.
    """
    if len(tokens) < 10:
        return None

    def _pass(seq: list[str]) -> float:
        factors = 0.0
        types: set[str] = set()
        count = 0
        for tok in seq:
            count += 1
            types.add(tok)
            if len(types) / count <= threshold:
                factors += 1.0
                types = set()
                count = 0
        if count > 0:
            ttr = len(types) / count
            if ttr < 1.0:
                factors += (1.0 - ttr) / (1.0 - threshold)
        if factors == 0:
            return float(len(seq))
        return len(seq) / factors

    return round((_pass(tokens) + _pass(tokens[::-1])) / 2.0, 1)


def _ngram_repairs(tokens: list[str]) -> tuple[int, int]:
    """(repetition_count, ngram_repair_count).

    repetition_count: bezpośrednie powtórzenie n-gramu (n=1..4).
    ngram_repair_count: powtórzenie n-gramu w odległości <= 5 słów (spec 5.2
    reguła 1); powtórzenia bezpośrednie też są autokorektą.
    Dłuższe n-gramy mają pierwszeństwo, dopasowania nie nakładają się.
    """
    n_tokens = len(tokens)
    used = [False] * n_tokens
    repetitions = 0
    repairs = 0
    for n in (4, 3, 2, 1):
        for i in range(n_tokens - n):
            if any(used[i : i + n]):
                continue
            gram = tokens[i : i + n]
            # szukaj tej samej sekwencji zaczynającej się w odległości <= 5 słów
            for j in range(i + n, min(i + n + 5, n_tokens - n + 1)):
                if any(used[j : j + n]):
                    continue
                if tokens[j : j + n] == gram:
                    for k in list(range(i, i + n)) + list(range(j, j + n)):
                        used[k] = True
                    repairs += 1
                    if j == i + n:
                        repetitions += 1
                    break
    return repetitions, repairs


def _false_starts(words: list[dict]) -> int:
    """Fragment przerwany pauzą >= 300 ms i wznowiony innym słowem funkcyjnym."""
    count = 0
    for prev, cur in zip(words, words[1:]):
        gap = cur["start"] - prev["end"]
        if gap < FALSE_START_PAUSE_S:
            continue
        prev_tok = re.sub(r"[^a-z']", "", prev["word"].lower())
        cur_tok = re.sub(r"[^a-z']", "", cur["word"].lower())
        # fragment bez zakończenia zdania (brak interpunkcji końcowej)...
        if prev["word"].strip().endswith((".", "!", "?")):
            continue
        # ...wznowiony innym słowem funkcyjnym niż to, na którym się urwał
        if cur_tok in FUNCTION_WORDS and cur_tok != prev_tok:
            count += 1
    return count


def _marker_count(tokens: list[str], markers: list[str]) -> int:
    count = 0
    for m in markers:
        phrase = _tokenize(m)
        n = len(phrase)
        if n == 0:
            continue
        count += sum(
            1 for i in range(len(tokens) - n + 1) if tokens[i : i + n] == phrase
        )
    return count


def compute_language_metrics(
    transcript: str,
    words: list[dict] | None,
    repair_markers: list[str] | None = None,
) -> dict:
    tokens = _tokenize(transcript)
    if not tokens:
        return {}

    repetitions, ngram_repairs = _ngram_repairs(tokens)
    false_starts = _false_starts(words or [])
    markers = _marker_count(tokens, repair_markers or [])

    m: dict = {
        "repetition_count": repetitions,
        "false_start_count": false_starts,
        "repair_count": ngram_repairs + false_starts + markers,
        "mtld": mtld(tokens),
    }

    top = _top_frequent_words()
    if top is not None:
        outside = [t for t in tokens if t not in top]
        m["word_frequency_profile"] = round(len(outside) / len(tokens), 3)

    nlp = get_nlp()
    if nlp is not None:
        doc = nlp(transcript)
        sents = [s for s in doc.sents if any(t.is_alpha for t in s)]
        if sents:
            m["sentence_count"] = len(sents)
            m["mean_length_utterance"] = round(
                sum(sum(1 for t in s if t.is_alpha) for s in sents) / len(sents), 2
            )
            sub_clauses = sum(1 for t in doc if t.dep_ in SUBORDINATE_DEPS)
            m["subordination_index"] = round(sub_clauses / len(sents), 3)

    return m


def clause_boundaries(
    transcript: str, words: list[dict] | None
) -> tuple[set[int], float]:
    """Indeksy w `words` rozpoczynające nową klauzulę (heurystyka AS-unit, spec 5.1).

    Granica: początek zdania, początek klauzuli podrzędnej (SUBORDINATE_DEPS)
    lub spójnik współrzędny łączący dwa orzeczenia (conj z własnym nsubj).
    To przybliżenie oparte na zależnościowym parserze spaCy, nie prawdziwa
    segmentacja AS-unit - stąd confidence: 1.0 gdy spaCy dostępny i sparsował
    tekst, 0.0 gdy spaCy niedostępny (wołający powinien wtedy pominąć metryki
    wymagające podziału na klauzule).
    """
    if not words:
        return set(), 0.0
    nlp = get_nlp()
    if nlp is None:
        return set(), 0.0
    doc = nlp(transcript)

    # przybliżone przypisanie słów Whispera do offsetów znakowych transkryptu
    starts: list[int] = []
    cursor = 0
    for wd in words:
        token = wd["word"]
        idx = transcript.find(token, cursor)
        if idx == -1:
            idx = cursor
        starts.append(idx)
        cursor = idx + len(token)

    def word_index_for_char(pos: int) -> int | None:
        for i in range(len(starts) - 1, -1, -1):
            if starts[i] <= pos:
                return i
        return None

    boundary_chars: set[int] = set()
    for sent in doc.sents:
        if any(t.is_alpha for t in sent):
            boundary_chars.add(sent[0].idx)
    for tok in doc:
        if tok.dep_ in SUBORDINATE_DEPS:
            boundary_chars.add(tok.left_edge.idx)
        elif tok.dep_ == "conj" and tok.pos_ in {"VERB", "AUX"}:
            if any(c.dep_ == "nsubj" for c in tok.children):
                left = tok.left_edge
                boundary_chars.add(left.idx if left.pos_ == "CCONJ" else tok.idx)

    indices = {word_index_for_char(c) for c in boundary_chars}
    indices.discard(None)
    return indices, 1.0


def content_lemmas(text: str) -> set[str]:
    """Lemmy słów treściowych - do dystansu leksykalnego w Paraphrase."""
    nlp = get_nlp()
    if nlp is None:
        return {t for t in _tokenize(text) if t not in FUNCTION_WORDS}
    doc = nlp(text)
    return {
        t.lemma_.lower()
        for t in doc
        if t.is_alpha and t.pos_ not in FUNCTION_POS and not t.is_stop
    }


def lexical_distance(text_a: str, text_b: str) -> float | None:
    """1 - Jaccard na lemmach treściowych (spec 7.1, Paraphrase)."""
    a = content_lemmas(text_a)
    b = content_lemmas(text_b)
    if not a or not b:
        return None
    return round(1.0 - len(a & b) / len(a | b), 3)
