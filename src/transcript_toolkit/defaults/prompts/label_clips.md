## Label each clip

You are given a stretch of an oral history interview, already split into clips. Each clip is a contiguous run of paragraphs on one specific micro-topic. Paragraph lines are prefixed with `[idx]` (paragraph index), an `[HH:MM:SS]` timestamp, a role marker `[Q]` (interviewer) or `[N]` (narrator), and a `(Xw)` word count.

Assign a label to each `## CLIP n` block. Return one result per CLIP as `{clip_number, label}`, where `clip_number` is the integer n.

Sections marked `PREVIOUS CLIP` / `NEXT CLIP` are context only — do NOT label them. Use them to keep each clip's label distinct from its neighbours.

## Label style

- One declarative phrase, 120 characters or fewer.
- Sentence case, neutral language.
- No period at the end.
- Do not reference the interviewee.

Example labels:

- Early life and upbringing
- Attending President Trump's inauguration
- The administration's first term priorities
- Efforts to stop the Keystone pipeline and influence the administration
- Regulating greenhouse gas emissions from power plants and the Clean Air Act
- The challenges of addressing race in Democratic Party politics
- Experience with Russia and Ukraine prior to joining the Obama administration
- Challenges of working for Amnesty International in Southern Asia