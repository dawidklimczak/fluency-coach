You are preparing the source material for one spontaneous-speaking fluency session. The learner understands English very well and thinks in English easily, but producing spontaneous speech is effortful and rambling. The single biggest problem this session's material must solve: the learner must never have to invent content on the spot. Your text GIVES them something to say; it never asks them to come up with something.

Learner's personal context (in Polish - their job, projects, interests, recurring situations; use it to anchor the seed_text in something real and specific to them):
{{personal_context}}

Domain for this session: {{domain}}

{{task_type_constraint}}

{{avoid_words}}

Phrases to reuse from this domain's recent sessions if they fit naturally (repetition across sessions is intentional - reuse at least two or three of these inside the new seed_text rather than inventing all-new phrasing):
{{repeat_chunks}}

Requirements:
- seed_text: 150-250 words in English. A narrative or a description of one concrete situation anchored in the learner's context above. It must read as something that HAPPENED or EXISTS, not as a set of questions or prompts. Vocabulary must be common, high-frequency, everyday English - no rare, technical, or literary words, no idioms, nothing a fluent-comprehension learner might not immediately recognize.
- guiding_questions: 4-5 questions in English, in the order the seed_text unfolds, that someone could use to retell the text without inventing new content.
- keywords: 8-12 content nouns or verbs that literally appear in seed_text.
- chunks: 6-8 multi-word phrases (not single words) that literally appear in seed_text, useful as ready-made building blocks for retelling it. For each, also write prompt_pl: a short situational description IN POLISH that would cue a learner to produce exactly that English phrase (e.g. for "stuck in traffic" -> "utknąłeś w korku i się spóźnisz").
- transfer_prompt: one new question from the same domain, about something NOT covered in seed_text. It must be answerable by reasoning, describing, or speculating about the domain in general - it must NOT require the learner to recall one specific real fact about their own life that isn't already given to them somewhere in this pack or in the personal context above.
- task_type: one of "narrative", "description", "argumentative" - classify what seed_text and transfer_prompt actually ask for.
- requires_personal_recall: true only if answering transfer_prompt truly requires digging up a specific real memory the learner would have to invent from scratch; false if it can be answered by describing, imagining, or reasoning about the domain instead.

Reply with JSON only, no markdown:
{"seed_text": "...", "guiding_questions": ["...", "..."], "keywords": ["...", "..."], "chunks": [{"text": "...", "prompt_pl": "..."}, {"text": "...", "prompt_pl": "..."}], "transfer_prompt": "...", "task_type": "...", "requires_personal_recall": false}
