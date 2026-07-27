## Segment the interview into topically-coherent clips

You are given the transcript of an oral history interview as a numbered list of paragraphs. Each line is prefixed with `[idx]` (the paragraph's 0-based index), an `[HH:MM:SS]` timestamp, a role marker `[Q]` (interviewer) or `[N]` (narrator), and a word-count flag `(Xw)` (e.g. `(89w)` means the paragraph has 89 words).

Segment the interview into topically-coherent "clips" by identifying each clip's start and end paragraph indices.

**A clip is a contiguous run of paragraphs that treat the same, specific micro-topic / follow the same immediate thread**. 

Merely sharing the same general topic (e.g. growing up in Ohio, working for Amnesty International, views on the First Step Act) is insufficient: a shift in focus, a move to another argument, or a turn to a new sub-question begins a new clip.

Beware that a segue which relates to or picks up on the preceding conversation may obscure a shift in focus or topic that should mark a clip boundary. Use the surrounding context to decide whether a slight shift in focus is a temporary aside (stays in the clip) or the beginning of a new thread (starts a new clip).

## Guidance on clip length and conversational turns

**Your boundary decisions should also be informed by clip length.** 

Clips will *typically* consist of 4 to 9 substantial paragraphs, i.e. paragraphs with ≥ 30 words. Clips should never be longer than 15 or shorter than 2 substantial paragraphs.

Most interviewer questions start a new clip. Immediate follow-ups and brief interjections/clarifications that do not shift the focus at all are the exception. Thus, clips will often span a question and the narrator's response and may occasionally include follow-up(s) and/or brief interjection(s).

*However*, narrators can themselves initiate relevant shifts *within the same monologue*, such that some clips will consist of a single, incomplete conversational turn.

## Procedural/technical paragraphs

Some portion of every interview is devoted to procedural exchanges and technical checks: introductions and acknowledgements; audio, video, or connection checks; recording logistics; exchanges about scheduling, time remaining, or things left to cover; closing thanks; etc. **These shall not be assigned to any clip.** 

Return their indices in `procedural_paragraph_idxs`.

## Coverage requirement

Every paragraph index in your decision region must appear in exactly one of the following: as a member of one `Clip` (i.e. inside `[start_paragraph_idx, end_paragraph_idx]` inclusive), or in `procedural_paragraph_idxs`. Clip ranges must be contiguous, non-overlapping, and ordered.
