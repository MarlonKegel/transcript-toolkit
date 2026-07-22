## Tag a clip to topics

You are given one clip from an oral history interview, together with a list of topics (below). The clip is a short, contiguous passage from an interview transcript. Its paragraphs are prefixed with a role marker `[Q]` (question/interviewer) or `[N]` (narrator/interviewee).

For every topic, judge how well this clip fits and assign a relevance score:

- **0** — does not belong in this topic
- **1** — could belong in this topic
- **2** — does belong in this topic

Focus on the gist of the clip. Do not overweight brief asides or mentions that are insignificant to the overall meaning or principal point of the clip. 

A topic tag is warranted under two conditions: 
    1) when the clip contains a specific mention of that topic or an associated concept, or an OSF program that deals with that topic. Only tag clips that are explicitly about the topics below and the associated concepts identified; and 
    2) when the mention of the topic/associated concept/OSF program is substantive. By substantive, I mean that the narrator says something meaningful about the topic, making it a central piece of their discussion. It should be something more than the narrator just referencing the specific phrase or including it in a list.

Score each topic independently, on its own merits. A clip may fit several topics, exactly one, or none. 
If there is no specific and/or substantive mention of any of these topics, associated concepts, or associated OSF projects and programs return 0 for every topic — do NOT force a fit. 
Do NOT assign more than 3 topics at score 2. When a clip belongs into more than 3 topics, select only the 3 best-fitting topics.