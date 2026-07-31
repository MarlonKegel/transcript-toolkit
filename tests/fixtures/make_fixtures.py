"""Generate the synthetic test transcripts (committed alongside this script).

Run once (from the repo root, any venv with python-docx):
    python tests/fixtures/make_fixtures.py

Entirely fake people and content. The three files exercise the naming conventions and every
parser quirk the import step must handle:
- Fake_Alpha_*_session{1,2}_SYNC.docx — a two-session narrator (pooling case), with an orphan
  paragraph before the first turn header, plain continuation paragraphs, a continuation with an
  embedded bare [HH:MM:SS], a stray mid-turn timestamp whose "label" is a sentence with a colon,
  and curly quotes.
- "Fake, Beta_SYNC.docx" — session-less id with comma-name filename normalization.
"""
from pathlib import Path

from docx import Document

HERE = Path(__file__).parent

ALPHA_S1 = [
    # orphan paragraph before any turn header (must be logged, not parsed)
    "Transcript of a fake interview generated for transcript-toolkit tests.",
    "[00:00:05] Q: Thank you for sitting down with me. Could you start by telling me where you "
    "grew up and what your childhood was like?",
    "[00:00:20] Alpha: I grew up in a small town by the river, the kind of place where everyone "
    "knew everyone else and the school had exactly one classroom per grade. My parents ran the "
    "local bakery, which meant I was up at five most mornings helping before class.",
    # plain continuation paragraph of the same turn (no timestamp header)
    "Looking back, that bakery taught me more about work than any job since. You learn what it "
    "means when something has to be ready by seven, no excuses, every single day of the year.",
    # continuation with an embedded bare timestamp (goes to sub_time_start, stripped from speech)
    "[00:02:10] And then when I was fourteen we moved to the city, which changed everything — "
    "new school, new friends, and my first library card, which I used constantly.",
    "[00:03:00] Q: What did you study when you got to university?",
    "[00:03:10] Alpha: History, though I drifted toward economic history by my second year. I had "
    "a professor who used to say something that stuck with me.",
    # stray mid-turn timestamp: label-shaped capture is a whole sentence -> folded into the turn
    "[00:03:45] What she kept repeating was this: institutions outlive the people who build them.",
    "[00:04:30] Q: Did that idea shape your later work at the foundation?",
    "[00:05:00] Alpha: Completely. When we set up the “first grants program” in the nineties, we "
    "were thinking in decades, not funding cycles. Everyone told us we were naive.",
    "Some of them were right, of course. The early grants went to organizations that vanished "
    "within two years, and we had to learn to ask harder questions without losing the ambition.",
    "[00:06:40] Q: Can you give an example of a grant that worked out?",
    "[00:07:00] Alpha: The teacher-training institute is the one I always come back to. Twenty "
    "years later its graduates run school districts across three countries, and it cost less "
    "than a single conference budget does today.",
]

ALPHA_S2 = [
    "[00:00:04] Q: Last time we ended with the teacher-training institute. What came next for you?",
    "[00:00:15] Alpha: The board asked me to take over the regional office, which meant moving "
    "again, this time with two children and a very patient spouse.",
    "The office was three rooms above a pharmacy. On my first day the fax machine caught fire, "
    "which felt like an omen, though of what I was never sure.",
    "[00:01:50] Q: How did the political changes of that decade affect the office's work?",
    "[00:02:05] Alpha: Everything sped up. Programs we had planned over five years suddenly had "
    "to happen in five months, because the window was open and nobody knew for how long.",
    "[00:03:20] Q: Were there moments you thought the window had closed?",
    "[00:03:30] Alpha: Twice. Once after the elections, and once when our registration was "
    "suspended for a season. Both times the local staff carried the work while we argued in "
    "meeting rooms, and both times they were the reason it survived.",
]

BETA = [
    "[00:00:06] Q: You trained as an engineer before moving into publishing. How did that happen?",
    "[00:00:18] Beta: By accident, honestly. I wrote a technical column for a friend's magazine "
    "and discovered I liked deadlines more than dams.",
    "The column ran for six years. Readers sent letters correcting my arithmetic, which kept me "
    "humble and occasionally kept me accurate.",
    "[00:01:40] Q: What was the publishing house like when you joined?",
    "[00:01:55] Beta: Chaotic and wonderful. We printed poetry nobody bought and manuals "
    "everybody bought, and the manuals paid for the poetry, which seemed like a fair economy.",
    "[00:03:05] Q: Did the censorship of that period touch your list?",
    "[00:03:15] Beta: Constantly. We became experts in the art of the missing chapter. Readers "
    "knew: when page ninety-nine was blank, the interesting part had been on page ninety-nine.",
    "[00:04:50] Q: What are you proudest of from those years?",
    "[00:05:00] Beta: The dictionary. Eleven years, four editors, one small fire. It is still on "
    "desks today, and every time I see a worn copy I think: worth it.",
]


# A transcript that was never SYNC'd: no timestamps anywhere, and a title page and preface
# before the interview starts, which is what these look like in practice. `toolkit summarize
# --unsynced` is the only thing that reads one.
GAMMA_RAW = [
    "A FAKE ORAL HISTORY PROJECT",
    "Oral History Interview with",
    "Gamma Fake",
    "Some Institute",
    "2025",
    "PREFACE",
    "The following oral history is the result of a recorded interview with Gamma Fake conducted "
    "by a fake interviewer on a date that never happened.",
    "Readers are asked to bear in mind that they are reading a transcript of the spoken word "
    "rather than written prose.",
    "Q: Today is a day that does not exist. Could you tell me how you came to the work you did?",
    "Gamma: Sideways, like most people. I studied one thing, was hired to do another, and spent "
    "twenty years discovering that the second one suited me.",
    "The part nobody tells you is how much of it is arranging chairs and booking rooms. The "
    "ideas are the easy half.",
    "Q: What kept you there?",
    "Gamma: The people, and the sense that the work would not happen if we stopped doing it. "
    "That is a hard thing to walk away from, and I did not, for a very long time.",
    # a sentence with a colon in it, which is a continuation and not a new speaker
    "There was one rule we kept: never promise what the budget cannot pay for.",
    "Q: And what would you tell somebody starting now?",
    "Gamma: That the work outlasts the plan, and the plan is still worth making.",
]


def write(name: str, paragraphs: list[str], folder: Path = HERE) -> None:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    folder.mkdir(parents=True, exist_ok=True)
    doc.save(folder / name)
    print(f"wrote {name} ({len(paragraphs)} paragraphs)")


if __name__ == "__main__":
    write("Fake_Alpha_20240101_session1_SYNC.docx", ALPHA_S1)
    write("Fake_Alpha_20240108_session2_SYNC.docx", ALPHA_S2)
    write("Fake, Beta_SYNC.docx", BETA)
    # In a subfolder, mirroring the workspace: the tests that copy every SYNC'd fixture into
    # data/ must not pick this one up, and neither must `toolkit import`.
    write("Fake_Gamma_Transcript.docx", GAMMA_RAW, HERE / "unsynced")
