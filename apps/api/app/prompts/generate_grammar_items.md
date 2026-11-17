You write SPOKEN grammar practice for one advanced Polish-speaking learner of English (reads fluently, about B2-C1, but speaking is not automatic yet). Tasks are shown as text; the learner answers ALOUD in one breath. The goal is live language: the learner must reach for the right sentence shape because of what they MEAN, never because they recall a rule.

The one skill to practise (a pairing meaning -> sentence shape):
- When I say this: {{meaning}}
- Sentence shape: {{pattern}}
- Example: {{example}}
- School name (for YOUR orientation only, never show it to the learner): {{name}}
- Typical trap for a Polish speaker (may be empty): {{trap}}

About the learner's world (use it for content, do not recite it): {{context}}

Sentences this learner already has for this skill (do not repeat their situations): {{existing}}

Write exactly these items:
- {{n_guided}} items with fmt "guided". prompt = a short real situation plus a question to the learner. cue = ONLY the first one to three words of a good answer, followed by " ..." (for example "If the printer ..."). The cue must never contain the verb forms the learner has to produce. hint stays empty.
- {{n_situation}} items with fmt "situation". prompt = a short real situation: someone says something to the learner, or the learner needs to tell someone something. Nothing else is visible. cue is empty. hint = a few plain words about the MEANING to express (for example "a plan you already have"), never a rule and never a shape.
- {{n_translate}} items with fmt "translate". prompt = ONE natural, colloquial POLISH sentence (the only place Polish is allowed) that a Pole would really say, and whose literal translation leads to the typical mistake for this skill. The learner says it in English. cue and hint are empty.
- {{n_fix}} items with fmt "fix". prompt = what a friend or colleague says, in English, containing exactly one typical learner error for this skill, written as: <first name> says: "..." with a different first name every time (for example: Tom says: "..."). The learner says it back correctly and naturally. cue and hint are empty.
- {{n_personal}} items with fmt "personal". prompt = an open question about the learner's own life or opinions that cannot be answered naturally without this sentence shape. The learner answers in one or two sentences. model_answer is one plausible example answer.

Rules for every item:
- Small, concrete, slightly vivid situations from work and everyday life (colleagues, clients, deadlines, flatmates, travel, money, health, family, small disasters). A different person, place and topic in every item. No textbook sentences, no "heat ice, it melts".
- The situation must make the meaning unmistakable, so that this shape is clearly the natural choice and a nearby shape would be wrong.
- Never show the finished answer, and never name the grammar: no school names ("present perfect", "second conditional", "gerund" and so on) and no formulas anywhere in prompt, cue or hint.
- State the facts the learner needs (when it started, whether it is still true, what really happened), so they never have to invent or guess them.
- Keep prompts short: at most two sentences, at most thirty words. The learner must be able to read them in a few seconds.
- model_answer = one natural spoken answer (contractions, normal phrasing), one sentence unless fmt is "personal". It MUST use the target sentence shape.
- accepted_variants = up to two other equally natural answers that also use the shape; may be empty.
- No digits, symbols or parentheses in anything the learner sees or says; write numbers as words.

Reply with JSON only, no markdown, in exactly this shape:
{"items": [{"fmt": "guided", "prompt": "...", "cue": "If the printer ...", "hint": "", "model_answer": "...", "accepted_variants": []}]}
