"""Trener tempa czytania: dopasowanie tekstu wzorcowego do tego, co padło.

Whisper zwraca timestampy słów - to wystarcza do lokalnego tempa per słowo.
Dopasowanie robimy difflib.SequenceMatcher na znormalizowanych tokenach
(bez nowych zależności), co przy okazji ujawnia słowa pominięte, dodane
i te, których Whisper nie rozpoznał jako wypowiedziane.

Uwaga na interpretację: "nierozpoznane" nie znaczy "źle wymówione" - Whisper
też się myli. To sygnał "nie wybrzmiało wyraźnie", nie ocena wymowy.
"""

import re
import statistics
from difflib import SequenceMatcher

# okno do liczenia tempa lokalnego; nieparzyste, żeby słowo było w środku
SPEED_WINDOW_WORDS = 5
# przerwa między słowami, od której mówimy o zacięciu podczas czytania
READING_PAUSE_S = 0.35

STATUS_SPOKEN = "spoken"
STATUS_UNCLEAR = "unclear"
STATUS_MISSED = "missed"


def normalize(token: str) -> str:
    """Do porównań: małe litery, bez interpunkcji, apostrofy zachowane."""
    return re.sub(r"[^a-z0-9']", "", token.lower())


def tokenize_reference(text: str) -> list[dict]:
    """Tokeny tekstu wzorcowego z zachowaniem oryginalnej pisowni i układu.

    `newline_before` pozwala frontendowi odtworzyć podział na akapity.
    """
    tokens: list[dict] = []
    for line_index, line in enumerate(text.split("\n")):
        first_in_line = True
        for raw in line.split():
            norm = normalize(raw)
            if not norm:
                continue
            tokens.append(
                {
                    "text": raw,
                    "norm": norm,
                    "newline_before": line_index > 0 and first_in_line,
                }
            )
            first_in_line = False
    return tokens


def align(reference_tokens: list[dict], spoken: list[dict]) -> tuple[list[dict], int]:
    """Przypisuje słowom wzorca czasy z transkrypcji.

    Zwraca (lista tokenów z czasem i statusem, liczba słów dodanych przez
    mówiącego - powtórzeń i wtrąceń, których nie ma w tekście).
    """
    ref_norm = [t["norm"] for t in reference_tokens]
    spoken_norm = [normalize(w["word"]) for w in spoken]

    aligned = [
        {**t, "start": None, "end": None, "status": STATUS_MISSED}
        for t in reference_tokens
    ]
    extra = 0

    matcher = SequenceMatcher(None, ref_norm, spoken_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                word = spoken[j1 + offset]
                aligned[i1 + offset].update(
                    start=float(word["start"]),
                    end=float(word["end"]),
                    status=STATUS_SPOKEN,
                )
        elif tag == "replace":
            # coś padło w tym miejscu, ale Whisper usłyszał inne słowo.
            # Gdy wypowiedzianych słów jest mniej niż wzorcowych, nadmiar
            # wzorca zostaje pominięciem - nic tam nie zabrzmiało.
            for offset in range(i2 - i1):
                src = spoken[j1 + offset] if j1 + offset < j2 else None
                if src is None:
                    continue  # zostaje STATUS_MISSED
                aligned[i1 + offset].update(
                    start=float(src["start"]),
                    end=float(src["end"]),
                    status=STATUS_UNCLEAR,
                    heard=src["word"].strip(),
                )
            extra += max(0, (j2 - j1) - (i2 - i1))
        elif tag == "insert":
            extra += j2 - j1
        # "delete" zostaje jako STATUS_MISSED

    return aligned, extra


def local_speeds(aligned: list[dict], window: int = SPEED_WINDOW_WORDS) -> None:
    """Dopisuje `wpm` - tempo lokalne w oknie kilku słów wokół każdego z nich.

    Liczone tylko dla słów z czasem; okno zwęża się przy krawędziach tekstu.
    """
    timed = [t for t in aligned if t["start"] is not None and t["end"] is not None]
    half = window // 2
    for index, token in enumerate(timed):
        lo = max(0, index - half)
        hi = min(len(timed), index + half + 1)
        chunk = timed[lo:hi]
        span = chunk[-1]["end"] - chunk[0]["start"]
        token["wpm"] = round(len(chunk) / span * 60.0, 1) if span > 0.05 else None


def _pauses(aligned: list[dict]) -> list[dict]:
    """Przerwy między kolejnymi wypowiedzianymi słowami - zacięcia w czytaniu."""
    timed = [t for t in aligned if t["start"] is not None and t["end"] is not None]
    out = []
    for previous, current in zip(timed, timed[1:]):
        gap = current["start"] - previous["end"]
        if gap >= READING_PAUSE_S:
            out.append({"before": current["text"], "duration": round(gap, 2)})
    return out


def compute(
    reference_text: str,
    spoken_words: list[dict],
    transcript: str,
    duration_s: float,
    phonation_s: float,
    target_wpm: int,
) -> tuple[list[dict], dict]:
    """Zwraca (tokeny do wyświetlenia, metryki zbiorcze)."""
    reference_tokens = tokenize_reference(reference_text)
    aligned, extra = align(reference_tokens, spoken_words)
    local_speeds(aligned)

    spoken_count = sum(1 for t in aligned if t["status"] == STATUS_SPOKEN)
    unclear_count = sum(1 for t in aligned if t["status"] == STATUS_UNCLEAR)
    missed_count = sum(1 for t in aligned if t["status"] == STATUS_MISSED)
    read_count = spoken_count + unclear_count

    speeds = [t["wpm"] for t in aligned if t.get("wpm") is not None]
    pauses = _pauses(aligned)

    # tempo brutto liczy całe nagranie (z pauzami), tempo artykulacji tylko
    # czas fonacji z VAD - różnica pokazuje, ile zjadły zacięcia
    wpm_gross = round(read_count / duration_s * 60.0, 1) if duration_s > 0 else None
    wpm_articulation = (
        round(read_count / phonation_s * 60.0, 1) if phonation_s > 0 else None
    )

    metrics = {
        "target_wpm": target_wpm,
        "wpm": wpm_gross,
        "wpm_articulation": wpm_articulation,
        "wpm_vs_target": (
            round(wpm_gross - target_wpm, 1) if wpm_gross is not None else None
        ),
        "steadiness": round(statistics.pstdev(speeds), 1) if len(speeds) > 1 else None,
        "fastest_wpm": max(speeds) if speeds else None,
        "slowest_wpm": min(speeds) if speeds else None,
        "reference_words": len(reference_tokens),
        "words_read": read_count,
        "spoken_count": spoken_count,
        "unclear_count": unclear_count,
        "missed_count": missed_count,
        "extra_count": extra,
        "accuracy": (
            round(spoken_count / len(reference_tokens), 3) if reference_tokens else None
        ),
        "duration_s": round(duration_s, 2),
        "phonation_s": round(phonation_s, 2),
        "phonation_ratio": (
            round(phonation_s / duration_s, 3) if duration_s > 0 else None
        ),
        "pause_count": len(pauses),
        "longest_pauses": sorted(pauses, key=lambda p: -p["duration"])[:5],
        "transcript_missing": not transcript,
    }
    return aligned, metrics
