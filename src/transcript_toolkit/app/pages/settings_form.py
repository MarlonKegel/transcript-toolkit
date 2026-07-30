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
    said = settings.explanations_for(project)

    readers: list[tuple[settings.Field, Callable[[], object], object]] = []
    with ui.column().classes("w-full gap-4"):
        for field in chosen:
            was = settings.value_at(current, field.path)
            # A setting that has not been given its own value here runs on whatever it falls back
            # to, so that is what the control has to show — and saving it writes it here.
            shown = was if was is not None else (
                settings.value_at(current, field.fallback) if field.fallback else None)
            says = settings.explained(said, field)
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(field.label).classes("text-sm font-medium")
                    if says:
                        info(says)
                if says:
                    ui.label(says).classes("text-xs opacity-70 max-w-2xl whitespace-pre-line")
                readers.append((field, _control(project, field, shown), was))

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
        return _house_rules(project, was)

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
        return _rollup(was or {}, field.step)

    box = ui.input(value="" if was is None else str(was)).props("dense outlined").classes("w-full")
    return lambda: box.value.strip()


def _house_rules(project, was) -> Callable[[], object]:
    """The extra instructions attached to a step's prompt: pick one the project already has, or
    write a new one here rather than being sent to make a file first.

    The toolkit's own justification instructions are not on the list (core/prompts.addendums):
    a step turns those on for its demo and off for a full run by itself.
    """
    from .prompts import edit_addendum, new_addendum

    state = {"value": was or None}
    options = [NONE_LABEL, *addendums(project)]
    if was and was not in options:
        options.insert(1, str(was))
    box = ui.select(options, value=was or NONE_LABEL).props("dense outlined").classes("w-full")

    def chosen(path: str) -> None:
        if path not in box.options:
            box.set_options([*box.options, path])
        box.set_value(path)
        state["value"] = path

    with ui.row().classes("gap-2"):
        ui.button("Write new house rules", icon="add", on_click=lambda: new_addendum(chosen)) \
            .props("dense flat")
        edit = ui.button("Edit these", icon="edit",
                         on_click=lambda: edit_addendum(box.value, chosen)).props("dense flat")

    def keep_edit_usable() -> None:
        edit.set_visibility(box.value != NONE_LABEL)

    box.on_value_change(keep_edit_usable)
    keep_edit_usable()
    return lambda: None if box.value == NONE_LABEL else box.value


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


def _rollup(was: dict, step: str) -> Callable[[], dict]:
    """When a topic (or a place) becomes one of an interview's tags.

    Two things are tuned here and everything else is a consequence of them: how many rarity bands
    the topics are split into, and the range the bars run over. The bars themselves are worked out
    from those, so nobody has to write out a list of numbers and keep it evenly spaced.

    The method sits behind a fold, opened only when the project is not on the recommended one.
    Most projects should never have to think about it, and `toolkit topics thresholds` is where
    the case for changing it is actually made — with pictures.
    """
    from ...core import thresholds

    items = thresholds.PLACES if step == "locations" else thresholds.TOPICS
    current = thresholds.parse(was or None, "this setting")
    picked = {"method": current.method}

    binned = ui.column().classes("gap-1")
    with binned:
        with ui.row().classes("items-center gap-2 flex-wrap"):
            bins_box = ui.number("Bands", min=1, max=20, step=1, precision=0,
                                 value=current.bins).props("dense outlined").classes("w-28")
            ui.label("from").classes("text-sm opacity-70")
            low_box = ui.number(min=0.5, max=100, step=0.5, value=current.low) \
                .props("dense outlined suffix=%").classes("w-28")
            ui.label("to").classes("text-sm opacity-70")
            high_box = ui.number(min=0.5, max=100, step=0.5, value=current.high) \
                .props("dense outlined suffix=%").classes("w-28")
        derived = ui.label().classes("text-xs opacity-70")

    flat_box = ui.number(
        thresholds.phrase("Every {item} needs this share of an interview's clips", items),
        min=0.5, max=100, step=0.5, value=current.threshold_pct) \
        .props("dense outlined suffix=%").classes("w-96")
    says = ui.label().classes("text-xs opacity-70 max-w-2xl")

    with ui.expansion("Use a different method",
                      value=current.method != thresholds.RECOMMENDED).classes("w-full"):
        choice = ui.radio({m: thresholds.method_label(m, items)
                           + (" — recommended" if m == thresholds.RECOMMENDED else "")
                           for m in thresholds.METHODS}, value=current.method).props("dense")
        ui.label("Which one to use is a judgement about your collection, and the way to make it "
                 "is to look: 'Compare how tags are decided', above, draws what each of these "
                 "would tag.").classes("text-xs opacity-70 max-w-2xl")

    def show() -> None:
        picked["method"] = choice.value
        flat = choice.value == thresholds.FLAT
        binned.set_visibility(not flat)
        flat_box.set_visibility(flat)
        says.set_text(thresholds.method_blurb(choice.value, items))
        derived.set_text(f"Bars: {_bars_text(bins_box.value, low_box.value, high_box.value)}")

    for box in (choice, bins_box, low_box, high_box):
        box.on_value_change(show)
    show()

    def read() -> dict:
        if picked["method"] == thresholds.FLAT:
            said = {"method": thresholds.FLAT, "threshold_pct": _number(flat_box.value)}
        else:
            said = {"method": picked["method"], "bins": int(_number(bins_box.value)),
                    "range": [_number(low_box.value), _number(high_box.value)]}
        return thresholds.parse(said, "these settings").as_config()   # refuse nonsense here

    return read


def _bars_text(bins, low, high) -> str:
    """The bars the numbers above would produce, so what is being set is visible while it is set."""
    from ...core import thresholds

    try:
        bars = thresholds.spread(float(low), float(high), int(bins))
    except (TypeError, ValueError, ToolkitError):
        return "—"
    return ", ".join(f"{_number_text(b)}%" for b in bars)


def _number(value):
    if value is None or str(value).strip() == "":
        raise ToolkitError("Fill in the percentage, or nothing can be saved.")
    number = float(value)
    return int(number) if number.is_integer() else number
