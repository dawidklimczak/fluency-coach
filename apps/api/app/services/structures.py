"""Detekcja struktur gramatycznych (spec 7.2, metryki 5.4).

Reguły na tagach, morfologii i drzewie zależności spaCy. Dla każdej struktury
funkcja zwraca listę indeksów tokenów-kotwic (pierwszy token konstrukcji);
z tego liczone są structure_used, structure_count i pre_structure_pause.

avoidance = brak wzorca pozytywnego w zadaniu wymagającym struktury.
Detekcja obejść jest celowo pominięta (spec: prostsze i wystarczające).
"""

import re

from .nlp import get_nlp

PRE_STRUCTURE_WINDOW_WORDS = 3

REPORT_VERBS = {
    "say", "tell", "ask", "explain", "mention", "claim", "admit", "insist",
    "reply", "announce", "warn", "promise", "complain", "suggest", "add",
}

SPECULATION_MODALS = {"must", "might", "may"}

HABITUAL_CUES = (
    "every", "always", "usually", "often", "whenever", "each summer",
    "as a child", "as a kid", "back then", "in those days", "growing up",
    "when i was", "those days", "at the time",
)


def _next_verb(doc, i: int, max_ahead: int = 4):
    """Pierwszy czasownik po tokenie i (pomijając przysłówki, negację, podmiot)."""
    for j in range(i + 1, min(i + 1 + max_ahead, len(doc))):
        t = doc[j]
        if t.pos_ in ("VERB", "AUX"):
            return t
        if t.pos_ not in ("ADV", "PART", "PRON", "PROPN", "NOUN", "DET"):
            return None
    return None


def _has_aux(token, lemma: str, tag: str | None = None) -> bool:
    return any(
        c.lemma_ == lemma and (tag is None or c.tag_ == tag)
        for c in token.children
        if c.dep_ in ("aux", "auxpass")
    )


def _aux_children(token) -> list:
    return [c for c in token.children if c.dep_ in ("aux", "auxpass")]


def _if_clause_tokens(sent) -> set[int]:
    """Indeksy tokenów należących do zdania podrzędnego z 'if' (poddrzewo advcl)."""
    out: set[int] = set()
    for t in sent:
        if t.lower_ == "if" and t.dep_ == "mark":
            head = t.head
            out.update(x.i for x in head.subtree)
    return out


def _sent_has_if(sent) -> bool:
    return any(t.lower_ == "if" for t in sent)


# --- detektory: doc -> list[int] (indeksy kotwic) ---------------------------


def _detect_future_will(doc):
    hits = []
    for t in doc:
        if t.lemma_ == "will" and t.tag_ == "MD":
            head = t.head
            if head.tag_ == "VB" and not (
                head.lemma_ == "have"
                and any(c.tag_ == "VBN" for c in head.children)
            ):
                # wyklucz will be + VBG (future continuous) i will have + VBN
                if head.lemma_ == "be" and any(
                    c.tag_ == "VBG" for c in head.children
                ):
                    continue
                if head.tag_ == "VBN":
                    continue
                hits.append(t.i)
            elif head.tag_ == "VBN" and _has_aux(head, "have", "VB"):
                continue  # future perfect
            elif head.tag_ == "VBG":
                continue  # future continuous
    return hits


def _detect_future_going_to(doc):
    hits = []
    for t in doc:
        if t.lemma_ == "go" and t.tag_ == "VBG" and _has_aux(t, "be"):
            if any(
                c.dep_ == "xcomp" and c.tag_ == "VB" for c in t.children
            ):
                hits.append(t.i)
    return hits


def _detect_future_continuous(doc):
    hits = []
    for t in doc:
        if t.tag_ == "VBG":
            auxes = _aux_children(t)
            if any(a.lemma_ == "will" for a in auxes) and any(
                a.lemma_ == "be" for a in auxes
            ):
                hits.append(min(a.i for a in auxes))
    return hits


def _detect_future_perfect(doc):
    hits = []
    for t in doc:
        if t.tag_ == "VBN":
            auxes = _aux_children(t)
            if any(a.lemma_ == "will" for a in auxes) and any(
                a.lemma_ == "have" and a.tag_ == "VB" for a in auxes
            ):
                hits.append(min(a.i for a in auxes))
    return hits


def _detect_past_simple(doc):
    hits = []
    for t in doc:
        if t.tag_ == "VBD" and t.dep_ not in ("aux", "auxpass"):
            hits.append(t.i)
    return hits


def _detect_past_continuous(doc):
    hits = []
    for t in doc:
        if t.tag_ == "VBG":
            auxes = _aux_children(t)
            if any(a.lemma_ == "be" and a.tag_ == "VBD" for a in auxes) and not any(
                a.lemma_ == "have" for a in auxes
            ):
                hits.append(min(a.i for a in auxes))
    return hits


def _detect_past_perfect(doc):
    hits = []
    for t in doc:
        if t.tag_ == "VBN":
            auxes = _aux_children(t)
            if any(a.lemma_ == "have" and a.tag_ == "VBD" for a in auxes):
                hits.append(min(a.i for a in auxes))
    return hits


def _detect_used_to(doc):
    hits = []
    for t in doc:
        if t.lower_ == "used" and t.tag_ in ("VBD", "VBN"):
            if _has_aux(t, "be") or _has_aux(t, "get"):
                continue  # "be used to" = przyzwyczajenie, inna konstrukcja
            xcomp = [c for c in t.children if c.dep_ == "xcomp" and c.tag_ == "VB"]
            if xcomp:
                hits.append(t.i)
    return hits


def _detect_would_habitual(doc):
    hits = []
    for sent in doc.sents:
        if _sent_has_if(sent):
            continue
        text = sent.text.lower()
        if not any(cue in text for cue in HABITUAL_CUES):
            continue
        for t in sent:
            if t.lemma_ == "would" and t.tag_ == "MD":
                head = t.head
                if head.tag_ == "VB" and head.lemma_ != "have":
                    hits.append(t.i)
    return hits


def _clause_main_verbs(sent, if_tokens: set[int]):
    """Orzeczenia poza if-clause; także orzeczniki nieczasownikowe z aux
    (np. "he would be broke" - root to przymiotnik)."""
    return [
        t
        for t in sent
        if t.i not in if_tokens
        and t.dep_ not in ("aux", "auxpass")
        and (t.pos_ in ("VERB", "AUX") or _aux_children(t))
    ]


def _detect_conditional(doc, variant: str):
    hits = []
    for sent in doc.sents:
        if_tokens = _if_clause_tokens(sent)
        if not if_tokens:
            continue
        if_verbs = [
            t
            for t in sent
            if t.i in if_tokens and t.pos_ in ("VERB", "AUX")
        ]
        main_verbs = _clause_main_verbs(sent, if_tokens)

        def if_has(tag=None, aux_lemma=None, aux_tag=None, modal=False):
            for v in if_verbs:
                if modal and v.tag_ == "MD":
                    return True
                if tag and v.tag_ == tag and v.dep_ not in ("aux", "auxpass"):
                    return True
                if aux_lemma and v.lemma_ == aux_lemma and (
                    aux_tag is None or v.tag_ == aux_tag
                ):
                    return True
            return False

        if_present = any(
            v.tag_ in ("VBZ", "VBP") for v in if_verbs
        ) and not any(v.tag_ == "MD" for v in if_verbs)
        if_past_perfect = any(
            v.tag_ == "VBN"
            and any(
                a.lemma_ == "have" and a.tag_ == "VBD" for a in _aux_children(v)
            )
            for v in if_verbs
            if v.dep_ not in ("aux", "auxpass")
        )
        if_past_simple = (
            any(
                v.tag_ == "VBD" and v.dep_ not in ("aux", "auxpass")
                for v in if_verbs
            )
            and not if_past_perfect
        ) or any(
            v.dep_ in ("aux", "auxpass") and v.tag_ == "VBD" and v.lemma_ != "have"
            for v in if_verbs
        )
        if_would = any(v.lemma_ in ("would", "will") for v in if_verbs)

        def main_modal_perfect():
            for v in main_verbs:
                if v.tag_ == "VBN":
                    auxes = _aux_children(v)
                    if any(
                        a.lemma_ in ("would", "could", "might") for a in auxes
                    ) and any(a.lemma_ == "have" and a.tag_ == "VB" for a in auxes):
                        return v
            return None

        def main_modal_simple():
            for v in main_verbs:
                if v.tag_ == "VBN" and any(
                    a.lemma_ == "have" for a in _aux_children(v)
                ):
                    continue  # modal perfect - to conditional_3
                auxes = _aux_children(v)
                if any(
                    a.lemma_ in ("would", "could", "might") for a in auxes
                ) and not any(a.lemma_ == "have" for a in auxes):
                    return v
            return None

        def main_will():
            for v in main_verbs:
                auxes = _aux_children(v)
                if any(a.lemma_ == "will" for a in auxes):
                    return v
            return None

        def main_present():
            for v in main_verbs:
                if v.tag_ in ("VBZ", "VBP") and not _aux_children(v):
                    return v
                auxes = _aux_children(v)
                if auxes and all(a.tag_ in ("VBZ", "VBP") for a in auxes):
                    return v
            return None

        anchor = min(if_tokens)
        if variant == "conditional_0":
            if if_present and not if_would and main_present() is not None and main_will() is None:
                hits.append(anchor)
        elif variant == "conditional_1":
            if if_present and not if_would and main_will() is not None:
                hits.append(anchor)
        elif variant == "conditional_2":
            if if_past_simple and not if_would and main_modal_simple() is not None:
                hits.append(anchor)
        elif variant == "conditional_3":
            if if_past_perfect and main_modal_perfect() is not None:
                hits.append(anchor)
        elif variant == "conditional_mixed":
            mixed_a = if_past_perfect and main_modal_simple() is not None and main_modal_perfect() is None
            mixed_b = if_past_simple and not if_would and main_modal_perfect() is not None
            if mixed_a or mixed_b:
                hits.append(anchor)
    return hits


def _detect_modal_speculation_present(doc):
    hits = []
    for t in doc:
        if t.tag_ == "MD" and t.lemma_ in SPECULATION_MODALS:
            head = t.head
            # orzeczenie dowolnego typu (VB / be stuck / be waiting), byle nie
            # modal perfect (have + VBN) - to spekulacja o przeszłości
            has_have = head.lemma_ == "have" or any(
                a.lemma_ == "have" for a in _aux_children(head)
            )
            if not has_have:
                hits.append(t.i)
        # can't be / cannot be - spekulacja przez negację
        if t.lemma_ == "can" and t.tag_ == "MD":
            head = t.head
            negated = any(c.dep_ == "neg" for c in head.children)
            if negated and head.lemma_ == "be" and head.tag_ == "VB":
                hits.append(t.i)
        # could be (kopula) - spekulacja; could + inny VB to zdolność
        if t.lemma_ == "could" and t.tag_ == "MD" and t.head.lemma_ == "be":
            if t.head.tag_ == "VB":
                hits.append(t.i)
    return sorted(set(hits))


def _detect_modal_speculation_past(doc):
    hits = []
    for t in doc:
        if t.tag_ == "VBN":
            auxes = _aux_children(t)
            has_modal = any(
                a.lemma_ in ("must", "might", "may", "could", "can")
                for a in auxes
                if a.tag_ == "MD"
            )
            has_have = any(a.lemma_ == "have" and a.tag_ == "VB" for a in auxes)
            has_would = any(a.lemma_ == "would" for a in auxes)
            if has_modal and has_have and not has_would:
                hits.append(min(a.i for a in auxes))
    return hits


def _detect_passive_voice(doc):
    hits = []
    for t in doc:
        if t.dep_ == "auxpass":
            hits.append(t.i)
        elif t.dep_ == "nsubjpass" and not any(
            c.dep_ == "auxpass" for c in t.head.children
        ):
            hits.append(t.i)
    return sorted(set(hits))


def _detect_reported_speech(doc):
    hits = []
    for t in doc:
        if t.lemma_ in REPORT_VERBS and t.tag_ in ("VBD", "VBN"):
            if any(c.dep_ == "ccomp" for c in t.children):
                hits.append(t.i)
    return hits


def _detect_relative_clauses(doc):
    return [t.i for t in doc if t.dep_ == "relcl"]


def _detect_gerund_vs_infinitive(doc):
    """Dopełnienie czasownika: gerundium lub bezokolicznik po czasowniku głównym."""
    hits = []
    for t in doc:
        if t.pos_ != "VERB":
            continue
        for c in t.children:
            if c.dep_ in ("xcomp", "ccomp", "dobj") and c.tag_ == "VBG":
                hits.append(c.i)
            elif c.dep_ == "xcomp" and c.tag_ == "VB" and any(
                g.lower_ == "to" and g.dep_ == "aux" for g in c.children
            ):
                hits.append(c.i)
    return sorted(set(hits))


def _detect_wish_if_only(doc):
    hits = [t.i for t in doc if t.lemma_ == "wish" and t.pos_ == "VERB"]
    text = doc.text.lower()
    for m in re.finditer(r"\bif only\b", text):
        span = doc.char_span(m.start(), m.end())
        if span is not None:
            hits.append(span[0].i)
    return sorted(set(hits))


DETECTORS = {
    "future_will": _detect_future_will,
    "future_going_to": _detect_future_going_to,
    "future_continuous": _detect_future_continuous,
    "future_perfect": _detect_future_perfect,
    "past_simple": _detect_past_simple,
    "past_continuous": _detect_past_continuous,
    "past_perfect": _detect_past_perfect,
    "used_to": _detect_used_to,
    "would_habitual": _detect_would_habitual,
    "conditional_0": lambda d: _detect_conditional(d, "conditional_0"),
    "conditional_1": lambda d: _detect_conditional(d, "conditional_1"),
    "conditional_2": lambda d: _detect_conditional(d, "conditional_2"),
    "conditional_3": lambda d: _detect_conditional(d, "conditional_3"),
    "conditional_mixed": lambda d: _detect_conditional(d, "conditional_mixed"),
    "modal_speculation_present": _detect_modal_speculation_present,
    "modal_speculation_past": _detect_modal_speculation_past,
    "passive_voice": _detect_passive_voice,
    "reported_speech": _detect_reported_speech,
    "relative_clauses": _detect_relative_clauses,
    "gerund_vs_infinitive": _detect_gerund_vs_infinitive,
    "wish_if_only": _detect_wish_if_only,
}


def detect(structure_id: str, text: str) -> list[int] | None:
    """Indeksy tokenów-kotwic albo None, gdy NLP niedostępne / brak detektora."""
    nlp = get_nlp()
    if nlp is None or structure_id not in DETECTORS:
        return None
    doc = nlp(text)
    return DETECTORS[structure_id](doc)


def _structure_accuracy(structure_id: str, text: str) -> bool | None:
    """Poprawność formy - zbierana, nigdy nie pokazywana po próbie (spec 5.4).

    Tylko błędy o wysokiej pewności; None = brak danych do oceny.
    """
    lowered = " ".join(re.findall(r"[a-z']+", text.lower()))
    if structure_id in ("conditional_2", "conditional_3", "conditional_mixed"):
        # klasyczny błąd: "if I would have known" / "if I would know"
        if re.search(r"\bif \w+('\w+)? would\b", lowered):
            return False
    if structure_id == "used_to":
        if re.search(r"\buse to\b", lowered) and "used to" not in lowered:
            return False
    return None


def _anchor_word_index(text: str, words: list[dict], token_i: int) -> int | None:
    """Mapuje indeks tokenu spaCy na indeks słowa z timestampami Whispera.

    Best-effort: tokeny spaCy mapowane przez offset znakowy na chunki
    transcript.split(); zakładamy words[i] ~ chunk[i] (tak buduje je pipeline).
    """
    nlp = get_nlp()
    if nlp is None:
        return None
    chunks = text.split()
    if len(chunks) != len(words):
        return None
    doc = nlp(text)
    if token_i >= len(doc):
        return None
    char_pos = doc[token_i].idx
    pos = 0
    for i, ch in enumerate(chunks):
        start = text.index(ch, pos)
        end = start + len(ch)
        if start <= char_pos < end:
            return i
        pos = end
    return None


def pre_structure_pause(
    text: str, words: list[dict], anchor_token_i: int
) -> float | None:
    """Najdłuższa pauza w oknie 3 słów poprzedzających konstrukcję (spec 5.4)."""
    wi = _anchor_word_index(text, words, anchor_token_i)
    if wi is None or wi == 0:
        return None
    lo = max(0, wi - PRE_STRUCTURE_WINDOW_WORDS)
    gaps = [
        words[i + 1]["start"] - words[i]["end"] for i in range(lo, wi)
    ]
    if not gaps:
        return None
    return round(max(0.0, max(gaps)), 3)


def structure_metrics(
    structure_id: str, transcript: str, words: list[dict] | None
) -> dict:
    """Metryki 5.4 dla próby z target_structure."""
    anchors = detect(structure_id, transcript)
    if anchors is None:
        return {"structure_detection_unavailable": True}
    used = len(anchors) > 0
    m: dict = {
        "target_structure": structure_id,
        "structure_used": used,
        "structure_count": len(anchors),
        "avoidance": not used,
        "structure_accuracy": _structure_accuracy(structure_id, transcript),
    }
    if used and words:
        m["pre_structure_pause"] = pre_structure_pause(
            transcript, words, anchors[0]
        )
    return m
