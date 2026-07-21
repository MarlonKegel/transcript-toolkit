<!--
Optional, PROJECT-SPECIFIC consistency / terminology rules appended to a text-producing
step's prompt (currently label-clips). Off by default: enable per subproject by setting
`addendum_file: ../shared/docs/prompt_addendum.md` in that subproject's config.yaml.

Keep it to cross-cutting wording rules (terminology, abbreviations, spellings) — step-level
behaviour belongs in the step's own prompt. Editing this file invalidates the LLM cache for
any step that uses it, so changed clips re-run on the next pass.

Replace the example below with the rules for your corpus.
-->

## Consistency rules

- When naming the **organization** (the Open Society Foundations, formerly the Open Society Institute), always call it "OSF" — not "Open Society", "OSI", or "Open Society Institute". Leave the general concept of an "open society" unchanged.
