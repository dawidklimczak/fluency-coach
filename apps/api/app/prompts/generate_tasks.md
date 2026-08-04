You are generating speaking-drill tasks for an English fluency trainer aimed at a C1-comprehension user whose spoken production lags behind.

Module: {{module}}
Module description: {{module_description}}
Difficulty: {{difficulty}} on a 1-10 scale. Difficulty is a property of CONTENT (abstractness of the concept, unfamiliarity of the topic, required precision), never of time limits.
{{structure_instruction}}

Generate {{count}} tasks. Rules:
- Prompts must be answerable by an adult professional from everyday experience.
- No two prompts may share a topic.
- Keep each prompt to one or two sentences.
- If a target structure is given, the prompt must make that structure UNAVOIDABLE in a natural answer - never mention the structure by name. Example of a good third-conditional prompt: "What is the one decision that would have completely changed your career?"
{{payload_instruction}}

Reply with JSON only, no markdown:
{"tasks": [{"prompt_text": "...", "target_structure": null, "payload": null, "tags": ["..."]}]}
