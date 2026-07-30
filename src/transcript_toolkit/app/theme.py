"""The app's colours: the two the icon is drawn in, and the few things they imply.

The icon is deep navy on warm cream, so the app is too — navy for everything you can act on,
cream for the paper it sits on. The three state colours (something to know, something to fix,
something that failed) are chosen to sit on cream rather than taken from a default palette.

Both a light and a dark version, because the app follows whatever the Mac is set to. Dark
inverts the pair rather than dimming it: cream ink on navy paper.
"""
from __future__ import annotations

from nicegui import ui

NAVY = "#2A3E55"            # the icon's navy
CREAM = "#E7DFCC"           # the icon's cream

# Light: cream paper, navy ink. Dark: the same two, the other way round.
PAPER = "#F1EBDD"
CARD = "#FBF8F1"
INK = "#1F2C3A"
EDGE = "#DCD2BD"

PAPER_DARK = "#16212C"
CARD_DARK = "#1F2D3B"
INK_DARK = CREAM
EDGE_DARK = "#2E4155"

MID_NAVY = "#4E6A85"        # secondary actions, and quiet meta text on navy
OCHRE = "#8A6034"           # the one warm accent, used sparingly

GOOD = "#3F6B52"
BAD = "#A8443B"
CAUTION = "#8A6A22"

# Classes for the three kinds of panel a page puts things in. Used instead of naming colours at
# every call site, so the palette lives here only.
NOTE = "tk-note"            # something worth knowing
WARN = "tk-warn"            # something to fix before going on
FAIL = "tk-fail"            # something that went wrong

CSS = f"""
body {{ background:{PAPER}; color:{INK}; }}
body.body--dark {{ background:{PAPER_DARK}; color:{INK_DARK}; }}
.q-card {{ background:{CARD}; border:1px solid {EDGE}; box-shadow:none; }}
body.body--dark .q-card {{ background:{CARD_DARK}; border-color:{EDGE_DARK}; }}
.q-header {{ color:{CREAM}; }}
.tk-note {{ background:#E4EAF0; border-color:#C6D3E0; }}
.tk-warn {{ background:#F5EBD6; border-color:#E0CEA6; }}
.tk-fail {{ background:#F5DEDA; border-color:#E3BCB5; }}
body.body--dark .tk-note {{ background:#22323F; border-color:#33465A; }}
body.body--dark .tk-warn {{ background:#332C1C; border-color:#4C412A; }}
body.body--dark .tk-fail {{ background:#361F1C; border-color:#4E2E29; }}
.tk-good {{ color:{GOOD}; }}
body.body--dark .tk-good {{ color:#6FB08A; }}
.tk-bad {{ color:{BAD}; }}
body.body--dark .tk-bad {{ color:#D98A80; }}
.tk-caution {{ color:{CAUTION}; }}
body.body--dark .tk-caution {{ color:#D9B45E; }}
/* Anything you can type into looks like paper you can type on, against the cream ground. */
.q-field--outlined .q-field__control {{ background:#FFFFFF; }}
body.body--dark .q-field--outlined .q-field__control {{ background:#101A24; }}
.tk-terminal {{ background:{PAPER_DARK}; color:{CREAM}; }}
.tk-row + .tk-row {{ border-top:1px solid {EDGE}; }}
body.body--dark .tk-row + .tk-row {{ border-top-color:{EDGE_DARK}; }}
"""

# A list long enough to need scrolling, sized so about a dozen rows show at once — enough to see
# the shape of a collection without pushing what comes after it off the page.
LIST_HEIGHT = "max-height: 26rem"


def apply() -> None:
    """Set the palette for the page being drawn. Called by the page shell, once per page."""
    ui.colors(primary=NAVY, secondary=MID_NAVY, accent=OCHRE,
              positive=GOOD, negative=BAD, warning=CAUTION, info=MID_NAVY,
              dark=CARD_DARK, dark_page=PAPER_DARK)
    ui.add_css(CSS)
