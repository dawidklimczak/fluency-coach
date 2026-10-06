You are preparing a matched set of spontaneous-speaking questions for a bottleneck diagnostic. The learner will answer several different questions, one per condition, each answerable in about 60 seconds. To keep the comparison between conditions fair, every question in this set must be at the SAME level of abstraction, SAME approximate difficulty, and require the SAME type of answer (opinion/reasoning, not facts) - but they must be genuinely DIFFERENT questions, not paraphrases of each other.

Learner's personal context (in Polish - use only to avoid a topic requiring specialist knowledge they don't have, never to anchor a question in it):
{{personal_context}}

Requirements for every question:
- Answerable in about 60 seconds by reasoning, describing, or giving a simple opinion.
- No specialist knowledge, no dates, no numbers, no facts to look up.
- No single objectively correct answer.
- Everyday, high-frequency vocabulary only.
- Must not require recalling one specific real personal memory.

Fields:
- cold: one question, to be answered with no preparation at all.
- supplied_ideas_prompt: a DIFFERENT question of matching difficulty.
- supplied_ideas: exactly 3 short directions (2-4 words each, not full sentences) that could structure an answer to supplied_ideas_prompt - e.g. for "Are social media good for tourism?" -> ["visibility", "local economy", "overtourism"]. Never write full sentences here.
- self_plan: a third DIFFERENT question of matching difficulty, to be answered after the learner writes their own short plan.
- native_control: a fourth DIFFERENT question of matching difficulty, written in POLISH, meant to be answered in Polish (a same-type control question, not a translation of any question above).

Reply with JSON only, no markdown:
{"cold": "...", "supplied_ideas_prompt": "...", "supplied_ideas": ["...", "...", "..."], "self_plan": "...", "native_control": "..."}
