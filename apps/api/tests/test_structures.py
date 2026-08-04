"""Test krytyczny 13.4: detekcja struktur gramatycznych.

Dla każdej struktury 5 zdań pozytywnych i 5 negatywnych (w tym typowe
obejścia). Wymagana precyzja i czułość >= 0.9 - przy tej liczności oznacza
to komplet trafień. Fałszywie dodatnia detekcja zaniża avoidance i unieważnia
podsystem, więc ten test blokuje wdrożenie mapy cieplnej.
"""

import pytest

from app.services.nlp import nlp_available
from app.services.structures import DETECTORS, detect, structure_metrics

pytestmark = pytest.mark.skipif(
    not nlp_available(), reason="spaCy en_core_web_sm niedostępny"
)

CASES: dict[str, tuple[list[str], list[str]]] = {
    "future_will": (
        [
            "I think it will take about three months.",
            "She will call you tomorrow morning.",
            "We will see how it goes.",
            "The team will deliver the report on Friday.",
            "It will rain later today.",
        ],
        [
            "I finished the report yesterday.",
            "We are going to move in September.",
            "She wanted to call you earlier.",
            "The project took three months.",
            "I usually take the bus to work.",
        ],
    ),
    "future_going_to": (
        [
            "We are going to move in September.",
            "I am going to quit my job next month.",
            "They are going to renovate the whole office.",
            "She is going to study medicine.",
            "It is going to rain this afternoon.",
        ],
        [
            "I am going to the office right now.",
            "We went to the beach last summer.",
            "She will study medicine.",
            "They renovated the office last year.",
            "I was going home when it started to rain.",
        ],
    ),
    "future_continuous": (
        [
            "This time next week I will be sitting on a train.",
            "Tomorrow at nine we will be discussing the budget.",
            "She will be working from home on Friday.",
            "They will be traveling through Spain in July.",
            "At noon I will be presenting the results.",
        ],
        [
            "I will finish the report tomorrow.",
            "She was working from home on Friday.",
            "We are discussing the budget right now.",
            "They traveled through Spain in July.",
            "I am sitting on a train.",
        ],
    ),
    "future_perfect": (
        [
            "By June I will have finished the migration.",
            "She will have completed the course by then.",
            "By next year we will have doubled our revenue.",
            "They will have left before you arrive.",
            "I will have written the summary by Monday.",
        ],
        [
            "I will finish the migration in June.",
            "She has completed the course.",
            "We doubled our revenue last year.",
            "They had left before I arrived.",
            "I will be writing the summary on Monday.",
        ],
    ),
    "past_simple": (
        [
            "I left at seven and got there late.",
            "She bought a new laptop last week.",
            "We talked about the plan yesterday.",
            "The meeting ended after two hours.",
            "He was late for the interview.",
        ],
        [
            "I leave at seven every day.",
            "She buys her groceries online.",
            "We will talk about the plan tomorrow.",
            "The meetings usually end after an hour.",
            "He is always late for interviews.",
        ],
    ),
    "past_continuous": (
        [
            "I was reviewing the code when the call came.",
            "They were eating dinner when we arrived.",
            "She was working late that night.",
            "We were waiting for the results all morning.",
            "He was talking to a client at the time.",
        ],
        [
            "I reviewed the code before the call.",
            "They ate dinner before we arrived.",
            "She works late every night.",
            "We will be waiting for the results.",
            "He talked to a client this morning.",
        ],
    ),
    "past_perfect": (
        [
            "The deadline had already passed when I noticed.",
            "She had finished the report before the meeting.",
            "By the time we arrived, they had left.",
            "He had never seen the ocean before that trip.",
            "I realized I had forgotten my keys.",
        ],
        [
            "The deadline passed yesterday.",
            "She finished the report before the meeting started.",
            "They left when we arrived.",
            "He has never seen the ocean.",
            "I forgot my keys this morning.",
        ],
    ),
    "used_to": (
        [
            "I used to commute two hours a day.",
            "She used to live in Berlin.",
            "We used to play chess every evening.",
            "He used to smoke a lot.",
            "They used to visit us every summer.",
        ],
        [
            "I commuted two hours a day for years.",
            "She lived in Berlin for a decade.",
            "I am used to getting up early.",
            "He used the old printer yesterday.",
            "They visited us last summer.",
        ],
    ),
    "would_habitual": (
        [
            "Every summer we would drive to the coast.",
            "When I was a kid, my dad would read to me every night.",
            "Back then she would always arrive first.",
            "As a child I would spend hours drawing.",
            "In those days we would meet every Friday.",
        ],
        [
            "If I had more time, I would travel more.",
            "I would like a coffee, please.",
            "Every summer we drove to the coast.",
            "She would help you if you asked.",
            "We used to meet on Fridays.",
        ],
    ),
    "conditional_0": (
        [
            "If a meeting has no agenda, it runs long.",
            "If you heat water enough, it boils.",
            "If the server crashes, everyone complains.",
            "If I skip breakfast, I get grumpy.",
            "If the tests fail, the build stops.",
        ],
        [
            "If the build fails, I will roll it back.",
            "If I had more time, I would rewrite it.",
            "The meeting ran long because there was no agenda.",
            "When the server crashed, everyone complained.",
            "If I had asked earlier, I would have saved a week.",
        ],
    ),
    "conditional_1": (
        [
            "If the build fails, I will roll it back.",
            "If it rains tomorrow, we will stay home.",
            "If she calls, I will let you know.",
            "If the price drops, they will buy more.",
            "If you finish early, we will grab lunch.",
        ],
        [
            "If you heat water enough, it boils.",
            "If I had more time, I would rewrite it.",
            "When the build failed, I rolled it back.",
            "If I had asked earlier, I would have saved a week.",
            "It will probably rain tomorrow.",
        ],
    ),
    "conditional_2": (
        [
            "If I had more time, I would rewrite it.",
            "If she lived closer, she would visit more often.",
            "If we knew the answer, we could skip the research.",
            "If he asked nicely, I might help him.",
            "If they offered me the job, I would take it.",
        ],
        [
            "If the build fails, I will roll it back.",
            "If I had asked earlier, I would have saved a week.",
            "If you heat water enough, it boils.",
            "I had more time last year.",
            "She would visit more often back then, every single month.",
        ],
    ),
    "conditional_3": (
        [
            "If I had asked earlier, I would have saved a week.",
            "If she had studied, she would have passed the exam.",
            "If we had left on time, we could have caught the train.",
            "If he had told me, I might have reacted differently.",
            "If they had tested it, the bug would have been caught.",
        ],
        [
            "If I had more time, I would rewrite it.",
            "If the build fails, I will roll it back.",
            "I asked late and lost a week.",
            "She had studied hard before the exam.",
            "If I had studied law, I would be in a different city now.",
        ],
    ),
    "conditional_mixed": (
        [
            "If I had studied law, I would be in a different city now.",
            "If we had taken the funding, we would own nothing today.",
            "If she had caught that flight, she would be here now.",
            "If I knew him better, I would have invited him.",
            "If he had saved money, he would not be broke now.",
        ],
        [
            "If I had asked earlier, I would have saved a week.",
            "If I had more time, I would rewrite it.",
            "If the build fails, I will roll it back.",
            "I studied law and moved to a different city.",
            "If you heat water enough, it boils.",
        ],
    ),
    "modal_speculation_present": (
        [
            "She must be stuck in traffic.",
            "He might know the answer.",
            "They may be waiting outside.",
            "It could be a configuration issue.",
            "That can't be the right address.",
        ],
        [
            "She is stuck in traffic.",
            "He knows the answer.",
            "He might have forgotten the meeting.",
            "I can swim quite well.",
            "They waited outside for an hour.",
        ],
    ),
    "modal_speculation_past": (
        [
            "He might have forgotten the meeting.",
            "She must have taken the earlier train.",
            "They could have missed the announcement.",
            "It may have been a network glitch.",
            "He can't have finished it already.",
        ],
        [
            "He forgot the meeting.",
            "She must be stuck in traffic.",
            "They missed the announcement.",
            "If I had asked earlier, I would have saved a week.",
            "He has finished it already.",
        ],
    ),
    "passive_voice": (
        [
            "The parts are assembled in three factories.",
            "The decision was made without me.",
            "The server has been restarted twice.",
            "The invoice will be sent tomorrow.",
            "He was given a second chance.",
        ],
        [
            "Three factories assemble the parts.",
            "We made the decision without him.",
            "Someone restarted the server twice.",
            "I will send the invoice tomorrow.",
            "They gave him a second chance.",
        ],
    ),
    "reported_speech": (
        [
            "She said she was leaving the company.",
            "He told me the project had been canceled.",
            "They mentioned they would join us later.",
            "She explained that the numbers did not add up.",
            "He admitted he had made a mistake.",
        ],
        [
            "She is leaving the company.",
            "The project has been canceled.",
            "Join us later, please.",
            "The numbers do not add up.",
            "I made a mistake yesterday.",
        ],
    ),
    "relative_clauses": (
        [
            "The engineer who wrote this module left last year.",
            "The house that we rented had no heating.",
            "I met a woman whose brother runs the bakery.",
            "The tool which we use daily is free.",
            "The meeting that never ends is today.",
        ],
        [
            "The engineer left last year.",
            "We rented a house with no heating.",
            "Her brother runs the bakery.",
            "We use this tool daily.",
            "Who wrote this module?",
        ],
    ),
    "gerund_vs_infinitive": (
        [
            "I enjoy reading before bed.",
            "She avoided answering the question.",
            "He decided to sell the car.",
            "They keep changing the requirements.",
            "We agreed to postpone the launch.",
        ],
        [
            "I read before bed every night.",
            "She answered the question directly.",
            "He sold the car last month.",
            "The requirements changed again.",
            "The launch was postponed.",
        ],
    ),
    "wish_if_only": (
        [
            "I wish I had more free time.",
            "She wishes she had taken the job.",
            "If only we had started earlier.",
            "I wish it were summer already.",
            "He wishes he could travel more.",
        ],
        [
            "I want more free time.",
            "She regrets not taking the job.",
            "We should have started earlier.",
            "I hope it will be summer soon.",
            "He would like to travel more.",
        ],
    ),
}


def test_all_structures_have_cases():
    assert set(CASES) == set(DETECTORS)


@pytest.mark.parametrize("structure_id", sorted(CASES))
def test_structure_detection_precision_recall(structure_id):
    positives, negatives = CASES[structure_id]
    assert len(positives) == 5 and len(negatives) == 5

    tp = sum(1 for s in positives if detect(structure_id, s))
    fp = sum(1 for s in negatives if detect(structure_id, s))
    fn = len(positives) - tp

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    missed = [s for s in positives if not detect(structure_id, s)]
    false_hits = [s for s in negatives if detect(structure_id, s)]
    assert precision >= 0.9 and recall >= 0.9, (
        f"{structure_id}: precision={precision:.2f} recall={recall:.2f} "
        f"missed={missed} false_hits={false_hits}"
    )


def test_structure_metrics_avoidance():
    m = structure_metrics("conditional_3", "I asked late and lost a week.", None)
    assert m["structure_used"] is False
    assert m["avoidance"] is True

    m2 = structure_metrics(
        "conditional_3", "If I had asked earlier, I would have saved a week.", None
    )
    assert m2["structure_used"] is True
    assert m2["avoidance"] is False
    assert m2["structure_count"] == 1


def test_structure_accuracy_flags_would_in_if_clause():
    m = structure_metrics(
        "conditional_3",
        "If I would have known about it, I would have gone there.",
        None,
    )
    assert m["structure_accuracy"] is False


def test_pre_structure_pause():
    text = "well I think if I had asked earlier I would have saved a week"
    words = []
    t = 0.0
    for chunk in text.split():
        words.append({"word": chunk, "start": t, "end": t + 0.2})
        t += 0.25
    # długa pauza tuż przed "if"
    for wrd in words:
        if wrd["word"] == "if":
            break
    idx = next(i for i, x in enumerate(words) if x["word"] == "if")
    for j in range(idx, len(words)):
        words[j]["start"] += 0.8
        words[j]["end"] += 0.8

    m = structure_metrics("conditional_3", text, words)
    assert m["structure_used"] is True
    assert m.get("pre_structure_pause") == pytest.approx(0.85, abs=0.01)
