"""Self-contained HTML for the diags/ review artifacts.

Diags are what a human (often a non-technical colleague on a Mac with no Markdown renderer)
opens to judge a step's output. Every review file is a single `.html` page with its CSS inlined
here — double-clickable in any browser, no dependency and no external asset. These pages are NOT
model-facing and play no part in cache keys or demo fingerprints, so the format is free to change
(unlike `core/render.py`, whose text feeds the cache).

Each step's writer assembles its own body HTML (it owns its layout) and wraps it with
`document()`; shared pieces — escaping, the stylesheet, the role badge, a paragraph line, and the
per-interview index page — live here so the look stays consistent and DRY.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

ROLE_LETTER = {"Interviewer": "Q", "Narrator": "N", "Other": "O"}
_ROLE_CLASS = {"Q": "q", "N": "n", "O": "o"}

CSS = """
:root {
  --fg:#22303f; --bg:#f5f1e6; --muted:#6b7a88; --line:#d8cfba; --card:#ebe4d3;
  --accent:#2a3e55; --q:#8a6034; --n:#2a3e55; --o:#7a7268; --score:#3f6b52;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fg:#e7dfcc; --bg:#1b2735; --muted:#9aa8b4; --line:#33455a; --card:#22303f;
    --accent:#b9c9d8; --q:#d9a96a; --n:#9fc0dc; --o:#9aa8b4; --score:#6fb08a;
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }
main { max-width:840px; margin:0 auto; padding:2rem 1.25rem 4rem; }
h1 { font-size:1.5rem; margin:0 0 .25rem; }
.subtitle { color:var(--muted); margin:0 0 1.5rem; font-size:.9rem; }
.back { margin:0 0 1rem; font-size:.9rem; }
.back a { text-decoration:none; }
.back a:hover { text-decoration:underline; }
section { border:1px solid var(--line); border-radius:8px; padding:.4rem 1rem 1rem;
  margin:0 0 1rem; background:var(--card); }
section.proc, section.unassigned { background:transparent; border-style:dashed; }
h2 { font-size:1.05rem; margin:.75rem 0 .5rem; font-weight:650; }
h2 .meta, .meta { color:var(--muted); font-weight:400; font-size:.82rem; }
.para { margin:.3rem 0; }
.idx { color:var(--muted); font-variant-numeric:tabular-nums; font-size:.8rem; margin-right:.4rem; }
.idx::before { content:"["; } .idx::after { content:"]"; }
.ts { color:var(--muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.78rem; margin-right:.4rem; }
.role { display:inline-block; min-width:1.4em; text-align:center; border-radius:4px;
  font-size:.72rem; font-weight:700; padding:0 .3em; margin-right:.45rem; color:#fff; }
.role-q { background:var(--q); } .role-n { background:var(--n); }
.role-o { background:var(--o); } .role-x { background:var(--muted); }
.label { margin:.25rem 0 .75rem; }
.k { font-weight:700; }
.topics ul, ul.index { list-style:none; padding-left:0; margin:.3rem 0 .75rem; }
.topics li { margin:.15rem 0; }
ul.index li { margin:.2rem 0; }
.score { display:inline-block; background:var(--score); color:#fff; border-radius:4px;
  font-weight:700; font-size:.75rem; padding:0 .4em; margin-right:.35rem; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.82em;
  background:rgba(127,127,127,.15); padding:0 .3em; border-radius:3px; }
.just { color:var(--muted); }
blockquote { border-left:3px solid var(--line); margin:.5rem 0; padding:.1rem 0 .1rem 1rem; }
blockquote p { margin:.3rem 0; }
table { border-collapse:collapse; width:100%; font-size:.88rem; margin:.5rem 0 1.5rem; }
th, td { border:1px solid var(--line); padding:.3rem .5rem; text-align:left; }
th { background:var(--card); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
a { color:var(--accent); }
/* Transcript text, so it wraps: reading a clip must not mean scrolling sideways. */
pre { background:var(--bg); border:1px solid var(--line); border-radius:6px;
  padding:.75rem 1rem; font-size:.82rem; line-height:1.5;
  white-space:pre-wrap; overflow-wrap:anywhere; }
"""


def esc(s) -> str:
    """HTML-escape any value's text (transcript speech may contain <, >, &)."""
    return escape(str(s), quote=True)


BACK_LABEL = "All interviews"


def document(title: str, body: str, subtitle: str = "",
             back: tuple[str, str] | None = None) -> str:
    """A complete self-contained page. `title` is escaped; `body`/`subtitle` are trusted HTML the
    caller has already assembled (escape your text through `esc()` before passing it in).

    `back` is (href, label): the way out of a per-interview page, so reading through a review set
    does not need the browser's own Back button — the app opens these in a tab of their own.
    """
    sub = f'\n<p class="subtitle">{subtitle}</p>' if subtitle else ""
    up = f'<p class="back"><a href="{esc(back[0])}">&larr; {esc(back[1])}</a></p>\n' if back else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f"{up}<h1>{esc(title)}</h1>{sub}\n{body}\n</main>\n</body>\n</html>\n"
    )


def role_badge(role: str) -> str:
    letter = ROLE_LETTER.get(role, "?")
    return f'<span class="role role-{_ROLE_CLASS.get(letter, "x")}">{letter}</span>'


def effective_ts(r) -> str:
    """The paragraph's own sub-timestamp, else its turn timestamp (may be empty)."""
    return r.sub_time_start or r.turn_time_start


def para(idx: int, ts: str, role: str, speech: str) -> str:
    """One transcript line: `[idx] [ts] [role] speech`. The timestamp badge is dropped when empty."""
    ts_html = f'<span class="ts">{esc(ts)}</span>' if ts else ""
    return (f'<p class="para"><span class="idx">{idx}</span>'
            f'{ts_html}{role_badge(role)} {esc(speech)}</p>')


def write_index(path: Path, title: str, entries: list[tuple[str, str, str]]) -> Path:
    """A landing page linking per-interview review files. `entries` = (href, label, meta_html)."""
    items = []
    for href, label, meta in entries:
        m = f' <span class="meta">{meta}</span>' if meta else ""
        items.append(f'<li><a href="{esc(href)}">{esc(label)}</a>{m}</li>')
    body = '<ul class="index">\n' + "\n".join(items) + "\n</ul>"
    path.write_text(document(title, body))
    return path
