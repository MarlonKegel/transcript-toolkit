"""Settings as controls rather than as a file.

Each setting is drawn with the words config.yaml itself uses for it: the comment above a key in
that file is its explanation here (core/settings.explanations). Editing the comment changes what
the app says, because there is only one description of a setting and it lives in the file.

Saving writes back into config.yaml in place, so a project stays a folder somebody can open in
TextEdit and a person who prefers doing that loses nothing.
"""
from __future__ import annotations

from typing import Callable

import yaml
from nicegui import ui

from ...core import settings
from ...core.prompts import addendums
from ...errors import ToolkitError
from ..context import CONTEXT
from .common import guard, info

NONE_LABEL = "none"

STALE_NOTE = ("Changing a model, a prompt or a setting makes this step's demo out of date: the "
              "next full run asks you to try it out and read the result again first.")


def settings_form(step: str, fields: list[settings.Field] | None = None,
                  on_saved: Callable[[], None] | None = None, *, note: bool = True,
                  save_label: str = "Save these settings") -> None:
    """Every setting belonging to `step`, as controls. `fields` overrides the list (topics adds
    the rollup rule for the chosen topic list).

    `save_label` names the button. The settings drawer is drawn on every page, so its own Save
    must not read the same as the Save belonging to the page behind it.
    """
    project = CONTEXT.require_project()
    chosen = list(fields if fields is not None else settings.for_step(step))
    if not chosen:
        return
    try:
        text = project.config_path.read_text()
        current = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError) as e:
        guard(ToolkitError(f"Could not read the settings from {project.config_path}: {e}"))
        return
    said = settings.explanations(text)

    readers: list[tuple[settings.Field, Callable[[], object], object]] = []
    with ui.column().classes("w-full gap-4"):
        for field in chosen:
            was = settings.value_at(current, field.path)
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(field.label).classes("text-sm font-medium")
                    if field.path in said:
                        info(said[field.path])
                if field.path in said:
                    ui.label(said[field.path]).classes(
                        "text-xs opacity-70 max-w-2xl whitespace-pre-line")
                readers.append((field, _control(project, field, was), was))

        if note:
            ui.label(STALE_NOTE).classes("text-xs opacity-60 max-w-2xl")

        def save() -> None:
            changes: dict[str, object] = {}
            try:
                for field_, read, was_ in readers:
                    now = read()
                    if now != was_:
                        changes[field_.path] = now
            except ToolkitError as e:
                guard(e)
                return
            if not changes:
                ui.notify("Nothing to save — none of these have changed.")
                return
            try:
                settings.save(project, changes)
            except ToolkitError as e:
                guard(e)
                return
            ui.notify(f"Saved {len(changes)} setting{'s' if len(changes) != 1 else ''}.",
                      type="positive")
            if on_saved:
                on_saved()

        ui.button(save_label, icon="save", on_click=save) \
            .props("dense").classes("self-start")


def _control(project, field: settings.Field, was) -> Callable[[], object]:
    """Draw the control for one setting and return the way to read its value back."""
    if field.kind == settings.TOGGLE:
        box = ui.switch(value=bool(was))
        return lambda: bool(box.value)

    if field.kind in (settings.MODEL, settings.CHOICE):
        options = list(settings.choices_for(field))
        if was is not None and was not in options:     # a value we do not know is still theirs
            options.insert(0, str(was))
        box = ui.select(options, value=was if was in options else (options[0] if options else None)) \
            .props("dense outlined").classes("w-64")
        return lambda: box.value

    if field.kind == settings.PROMPT_FILE:
        options = [NONE_LABEL, *addendums(project)]
        if was and was not in options:
            options.insert(1, str(was))
        box = ui.select(options, value=was or NONE_LABEL).props("dense outlined").classes("w-full")
        return lambda: None if box.value == NONE_LABEL else box.value

    if field.kind == settings.WORDS:
        box = ui.input(value=", ".join(str(v) for v in (was or []))) \
            .props("dense outlined").classes("w-full")
        ui.label("Separate them with commas. Leave it empty for none.").classes("text-xs opacity-50")
        return lambda: _words(box.value)

    if field.kind == settings.NUMBERS:
        box = ui.input(value=", ".join(_number_text(v) for v in (was or []))) \
            .props("dense outlined").classes("w-full")
        ui.label("Numbers, separated by commas.").classes("text-xs opacity-50")
        return lambda: _numbers(box.value, field.label)

    if field.kind == settings.PAIRS:
        return _pairs(was or {})

    if field.kind == settings.ROLLUP:
        return _rollup(was or {})

    box = ui.input(value="" if was is None else str(was)).props("dense outlined").classes("w-full")
    return lambda: box.value.strip()


def _words(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _number_text(value) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _numbers(text: str, label: str) -> list:
    out = []
    for part in _words(text):
        try:
            out.append(int(part) if "." not in part else float(part))
        except ValueError as e:
            raise ToolkitError(f"'{part}' in {label} is not a number, so nothing was saved.") from e
    return out


def _pairs(was: dict) -> Callable[[], dict]:
    """A mapping, as rows you can add to and clear. Used for the spellings to standardise."""
    rows: list[dict] = []
    holder = ui.column().classes("w-full gap-1")

    def add(key: str = "", value: str = "") -> None:
        with holder, ui.row().classes("w-full items-center gap-2") as row:
            left = ui.input(value=key, placeholder="as the model writes it") \
                .props("dense outlined").classes("grow")
            ui.icon("arrow_forward").classes("opacity-50")
            right = ui.input(value=value, placeholder="how you want it") \
                .props("dense outlined").classes("grow")
            entry = {"from": left, "to": right, "row": row}
            rows.append(entry)
            ui.button(icon="close", on_click=lambda: _drop(entry)).props("flat dense round")

    def _drop(entry: dict) -> None:
        rows.remove(entry)
        holder.remove(entry["row"])

    for key, value in (was or {}).items():
        add(str(key), str(value))
    ui.button("Add one", icon="add", on_click=lambda: add()).props("flat dense")
    return lambda: {r["from"].value.strip(): r["to"].value.strip() for r in rows
                    if r["from"].value.strip()}


FLAT, BINNED = "flat", "binned"


def _rollup(was: dict) -> Callable[[], dict]:
    """The two rollup schemes, one control each, with only the chosen one's numbers showing."""
    scheme = (was or {}).get("scheme") or FLAT
    picked = ui.radio({FLAT: "One bar for every topic",
                       BINNED: "A lower bar for rarer topics"}, value=scheme).props("dense")
    flat_box = ui.number("Percent of an interview's clips", min=1, max=100, step=0.5,
                         value=(was or {}).get("threshold_pct") or 30) \
        .props("dense outlined").classes("w-64")
    bars = list((was or {}).get("thresholds") or [10, 12.5, 15, 17.5, 20, 22.5, 25, 27.5, 30])
    binned_box = ui.input("Bars, rarest topics first",
                          value=", ".join(_number_text(v) for v in bars)) \
        .props("dense outlined").classes("w-full")

    def show() -> None:
        flat_box.set_visibility(picked.value == FLAT)
        binned_box.set_visibility(picked.value == BINNED)

    picked.on_value_change(show)
    show()

    def read() -> dict:
        if picked.value == FLAT:
            return {"scheme": FLAT, "threshold_pct": _number(flat_box.value)}
        return {"scheme": BINNED, "thresholds": _numbers(binned_box.value, "the bars")}

    return read


def _number(value):
    if value is None or str(value).strip() == "":
        raise ToolkitError("Fill in the percentage, or nothing can be saved.")
    number = float(value)
    return int(number) if number.is_integer() else number
