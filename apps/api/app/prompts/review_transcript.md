Below is a transcript of a spoken English conversation between a Polish-speaking learner of English and a conversation partner (usually an AI assistant). Your job is to find the learner's real grammar mistakes so they can be turned into practice.

First decide which lines are the learner's. The learner is the non-native speaker; labels such as "You said", "You:", "Me:", "User:" mark the learner, and labels such as "ChatGPT said", "Assistant:", "AI:" mark the partner. If there are no labels, the learner is the one who answers questions and makes non-native mistakes. Ignore everything the partner says, including any feedback or corrections the partner gives.

The skills the learner is working on (id: meaning -> sentence shape):
{{catalogue}}

Find up to ten grammar mistakes in the learner's lines.
- Only real grammar mistakes in sentence shape: tense, auxiliary, word order, verb pattern, conditionals, questions and so on. Ignore vocabulary, style, filler words, false starts, self-corrections, and anything that looks like a speech-recognition glitch. Ignore missing or wrong articles.
- Prefer mistakes that match a skill from the list, and mistakes that repeat.
- For each: said = the learner's sentence or clause containing the mistake, quoted exactly but trimmed to one sentence; corrected = the closest natural correct version of what the learner meant; skill_id = the id of the matching skill from the list, or an empty string if none fits; explanation = one short sentence in simple English tying the form to the meaning, without school names of structures.

Also list in used_well the ids of skills from the list that the learner clearly used correctly and spontaneously at least once (not merely repeating the partner's words).

summary = two short sentences in simple English: what already works well in the learner's speech, and the one pattern most worth practising next.

If the text is not a conversation or contains no learner speech, return empty lists and say so in summary.

Transcript:
{{transcript}}

Reply with JSON only, no markdown:
{"findings": [{"skill_id": "", "said": "...", "corrected": "...", "explanation": "..."}], "used_well": ["..."], "summary": "..."}
