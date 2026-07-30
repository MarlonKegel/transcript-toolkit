"""The regions the locations step may use, edited in the app.

`locations/regions.yaml` is a strict vocabulary: it is injected into the prompt AND turned into
the schema enum the model must answer from, so a region that is not on this list cannot be
returned. That makes it the one editable list where a typo is not a small mistake — it changes
what the model is allowed to say, and it makes every recorded demo stale.

The other half of the story is `region_to_country.csv`: the `map` step refuses a region it has
no countries for. So saving checks the two against each other and says which regions are not
mapped, rather than letting the run find out three steps later.
"""
from __future__ import annotations

import yaml
from nicegui import ui

from ...core.config import load_step_config
from ...errors import ToolkitError
from ..context import CONTEXT
from .common import guard
from .prompts import text_area

INTRO = ("The only regions the model may answer with. It is sent as part of the prompt and "
         "enforced on the way back, so nothing outside this list can ever be tagged. One region "
         "per line.")

STALE_NOTE = ("Saving makes this step's demo out of date, which is what you want: try it out on "
              "the demo clips again and read the result before running the whole collection.")

HEIGHT = "24rem"


def regions_editor(on_saved=None) -> None:
    project = CONTEXT.require_project()
    try:
        cfg = load_step_config(project, "locations")
        path = project.root / cfg["regions_file"]
        current = _read(path)
    except (ToolkitError, OSError, yaml.YAMLError) as e:
        guard(ToolkitError(f"Could not read the region list: {e}"))
        return

    ui.label(INTRO).classes("text-sm opacity-80 max-w-2xl")
    ui.label(str(path.relative_to(project.root))).classes("text-xs opacity-60 font-mono")
    box = text_area("\n".join(current), HEIGHT)
    ui.label("Countries are not listed here — the model writes those freely, so a country that "
             "no longer exists can still be tagged.").classes("text-xs opacity-60 max-w-2xl")
    ui.label(STALE_NOTE).classes("text-xs opacity-60 max-w-2xl")
    unmapped = ui.label().classes("text-xs tk-caution max-w-2xl")
    _report_unmapped(project, cfg, current, unmapped)

    def save() -> None:
        names = [line.strip() for line in box.value.split("\n") if line.strip()]
        try:
            _write(path, names)
        except (ToolkitError, OSError) as e:
            guard(e if isinstance(e, ToolkitError) else ToolkitError(f"Could not save {path}: {e}"))
            return
        ui.notify(f"Saved {len(names)} regions. Run the demo again to see what they do.",
                  type="positive")
        _report_unmapped(project, cfg, names, unmapped)
        if on_saved:
            on_saved()

    ui.button("Save these regions", icon="save", on_click=save).props("dense").classes("mt-2")


def _read(path) -> list[str]:
    if not path.exists():
        raise ToolkitError(f"{path} is not there. Restore it from another project, or reinstall "
                           f"the toolkit's copy with `toolkit init --force` in a fresh folder.")
    names = yaml.safe_load(path.read_text())
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ToolkitError(f"{path} is not a plain list of region names.")
    return names


def _write(path, names: list[str]) -> None:
    """Write the list back, keeping the file's own explanation of itself at the top.

    The header comment says what the file is for and that it feeds both the prompt and the
    schema. Rewriting the file from the app must not be the thing that deletes it.
    """
    if not names:
        raise ToolkitError("The region list cannot be empty — the step needs a vocabulary to "
                           "give the model.")
    seen = {}
    for name in names:
        if name in seen:
            raise ToolkitError(f"'{name}' is on the list twice, so nothing was saved.")
        seen[name] = True
    header = [line for line in path.read_text().split("\n") if line.startswith("#")]
    # yaml writes the list rather than us: a region name is free text, and one containing a colon
    # or a leading quote would otherwise save a file nothing can read back.
    body = yaml.safe_dump(names, allow_unicode=True, default_flow_style=False, sort_keys=False)
    path.write_text("\n".join([*header, body]))


def _report_unmapped(project, cfg: dict, names: list[str], label) -> None:
    """Which of these regions the `map` step has no countries for. It refuses one it does not
    know, so saying so here is the difference between a warning and a failed run later."""
    from ...steps.locations.map import load_region_map

    try:
        mapping = load_region_map(project.root / cfg["region_map_file"])
    except ToolkitError:
        label.set_text("")
        return
    missing = [name for name in names if name not in mapping]
    label.set_text(
        f"Not in {cfg['region_map_file']}: {', '.join(missing)}. Tagging works, but "
        f"'Expand regions into countries' stops when it meets one of these — add a row for each "
        f"of them, or the marker NONE if it should expand to nothing."
        if missing else "")
