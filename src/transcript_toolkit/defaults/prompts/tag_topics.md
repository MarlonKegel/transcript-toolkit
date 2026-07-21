## Tag a clip to topics

You are given one clip from an oral history interview, together with a list of topics and their definitions (below). The clip is a short, contiguous passage from an interview transcript. Its paragraphs are prefixed with a role marker `[Q]` (question/interviewer) or `[N]` (narrator/interviewee).

For every topic, judge how well this clip fits and assign a relevance score:

- **0** — does not belong in this topic
- **1** — could belong in this topic
- **2** — does belong in this topic

Focus on the gist, main subject or story of the clip. Do not overweight brief asides or mentions that are insignificant to the overall meaning or principal point of the clip.

Score each topic independently, on its own merits. A clip may fit several topics, exactly one, or none. If the clip fits none of the listed topics, return 0 for every topic — do not force a fit. Do NOT assign more than 3 topics at score 2. When a clip belongs into more than 3 topics, select only the 3 best-fitting topics.
