#!/usr/bin/env python3
"""Render the docs into a static site in _site/ (used by .github/workflows/pages.yml).

Two audiences: people, who get a readable website instead of GitHub's file browser; and chat
assistants, which fetch ordinary web pages far more reliably than github.com. llms.txt and
llms-full.txt are copied to the site root so the conventional URLs work too.

    pip install markdown && python scripts/build_site.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_docs_bundle import DOCS, ROOT  # noqa: E402

OUT = ROOT / "_site"
SITE_TITLE = "transcript-toolkit"

CSS = """
:root { --fg:#1a1a1a; --bg:#fff; --muted:#666; --line:#e3e3e6; --accent:#2563eb; --card:#f7f7f8; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6e6e6; --bg:#16181d; --muted:#9aa0aa; --line:#2c2f36; --accent:#6ea8fe;
          --card:#1e2127; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.65 -apple-system,
       BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }
.wrap { max-width: 860px; margin: 0 auto; padding: 2rem 1.25rem 5rem; }
nav { border-bottom:1px solid var(--line); background:var(--card); }
nav .wrap { padding: .75rem 1.25rem; display:flex; gap:1rem; flex-wrap:wrap; align-items:center; }
nav a { color:var(--fg); text-decoration:none; font-size:.9rem; }
nav a.brand { font-weight:700; }
nav a:hover { color:var(--accent); }
h1 { font-size:1.9rem; margin:1.5rem 0 .5rem; }
h2 { font-size:1.3rem; margin:2rem 0 .5rem; border-bottom:1px solid var(--line); padding-bottom:.3rem; }
h3 { font-size:1.05rem; margin:1.5rem 0 .4rem; }
a { color:var(--accent); }
code { background:rgba(127,127,127,.15); padding:.1em .35em; border-radius:3px;
       font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.88em; }
pre { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:1rem;
      overflow-x:auto; }
pre code { background:none; padding:0; font-size:.85rem; line-height:1.5; }
table { border-collapse:collapse; width:100%; margin:1rem 0; display:block; overflow-x:auto; }
th, td { border:1px solid var(--line); padding:.4rem .6rem; text-align:left; font-size:.92rem; }
th { background:var(--card); }
blockquote { border-left:3px solid var(--accent); margin:1rem 0; padding:.2rem 0 .2rem 1rem;
             color:var(--muted); }
.ai { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--accent);
      border-radius:8px; padding:1rem 1.25rem; margin:1.5rem 0; }
footer { color:var(--muted); font-size:.85rem; margin-top:3rem; border-top:1px solid var(--line);
         padding-top:1rem; }
"""

NAV = """<nav><div class="wrap">
<a class="brand" href="{root}index.html">transcript-toolkit</a>
<a href="{root}docs/SETUP.html">Setup</a>
<a href="{root}docs/WORKFLOW.html">Workflow</a>
<a href="{root}docs/CONFIG.html">Config</a>
<a href="{root}docs/TROUBLESHOOTING.html">Troubleshooting</a>
<a href="{root}llms-full.txt">All docs (for AI)</a>
<a href="https://github.com/MarlonKegel/transcript-toolkit">GitHub</a>
</div></nav>"""


def page(title: str, body_html: str, depth: int) -> str:
    root = "../" * depth
    return (f"<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{title} · {SITE_TITLE}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
            f"{NAV.format(root=root)}\n<div class=\"wrap\">\n{body_html}\n"
            f"<footer>Generated from the repository. "
            f"<a href=\"{root}llms-full.txt\">Complete docs as one text file</a> — paste that link "
            f"into ChatGPT, Claude or Gemini to ask questions about the toolkit.</footer>\n"
            f"</div>\n</body>\n</html>\n")


def render(md_text: str) -> str:
    import markdown
    html = markdown.markdown(md_text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    # in-repo .md links must point at the generated .html pages
    return re.sub(r'(href="[^"]+?)\.md(#[^"]*)?"',
                  lambda m: f'{m.group(1)}.html{m.group(2) or ""}"', html)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    for rel in ("llms.txt", "llms-full.txt"):
        shutil.copyfile(ROOT / rel, OUT / rel)

    for rel, _desc in DOCS:
        src = ROOT / rel
        out_rel = "index.html" if rel == "README.md" else rel[:-3] + ".html"
        dest = OUT / out_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        title = "Home" if rel == "README.md" else Path(rel).stem
        dest.write_text(page(title, render(src.read_text()), depth=len(Path(out_rel).parts) - 1))
        print(f"wrote _site/{out_rel}")

    (OUT / ".nojekyll").write_text("")      # serve paths as-is, no Jekyll processing
    return 0


if __name__ == "__main__":
    sys.exit(main())
