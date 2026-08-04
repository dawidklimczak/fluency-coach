"""Sprawdzenie słów zakazanych (Describe Without the Word).

Docelowo lematyzacja spaCy (faza 3). Do tego czasu: heurystyczne rozszerzenie
każdego słowa zakazanego o typowe formy fleksyjne i sprowadzenie tokenów
transkrypcji do formy bazowej prostymi regułami.
"""

import re


def _variants(word: str) -> set[str]:
    w = word.lower().strip()
    out = {w}
    out.add(w + "s")
    out.add(w + "es")
    if w.endswith("y"):
        out.add(w[:-1] + "ies")
        out.add(w[:-1] + "ied")
    out.add(w + "ed")
    out.add(w + "d")
    out.add(w + "ing")
    if len(w) > 2:
        out.add(w + w[-1] + "ing")  # run -> running
        out.add(w + w[-1] + "ed")
    if w.endswith("e"):
        out.add(w[:-1] + "ing")  # make -> making
    return out


def find_forbidden(transcript: str, forbidden_words: list[str]) -> list[str]:
    """Zwraca listę zakazanych słów/fraz użytych w transkrypcji."""
    text = transcript.lower()
    tokens = set(re.findall(r"[a-z']+", text))
    hits: list[str] = []
    for fw in forbidden_words:
        fw_norm = fw.lower().strip()
        if " " in fw_norm:
            if fw_norm in text:
                hits.append(fw)
            continue
        if tokens & _variants(fw_norm):
            hits.append(fw)
    return hits
