"""Choosing a folder without typing a path.

A browser cannot hand a web page a folder from Finder — file inputs give it the *contents* of
what you pick, never a path. But the app's server is this Mac, so the folder list can come from
the server instead: this is a Finder-shaped view of the real filesystem, and clicking through it
produces a real path. Typing one still works; most people should not have to.

Only directories are listed — the thing being chosen is always a folder.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from nicegui import ui

MAX_ENTRIES = 500          # a folder with more than this is not one anybody is picking from


def shortcuts() -> list[tuple[str, Path]]:
    """The places worth one click. Documents first: that is where a project belongs."""
    home = Path.home()
    places = [("Home", home)]
    for label in ("Documents", "Desktop", "Downloads"):
        if (home / label).is_dir():
            places.append((label, home / label))
    return places


def subfolders(where: Path) -> list[Path]:
    """The folders inside `where`, hidden ones left out, alphabetical."""
    try:
        entries = sorted(p for p in where.iterdir()
                         if p.is_dir() and not p.name.startswith("."))
    except (PermissionError, OSError):
        return []
    return entries[:MAX_ENTRIES]


def is_workspace(path: Path) -> bool:
    return (path / ".toolkit" / "project.json").exists()


def choose_folder(on_pick: Callable[[str], None], *, start: str | Path | None = None,
                  title: str = "Choose a folder",
                  hint: str = "") -> None:
    """Open the folder browser. `on_pick` gets the chosen path when the user confirms."""
    here = Path(start).expanduser() if start else Path.home()
    if not here.is_dir():
        here = Path.home()
    state = {"path": here.resolve()}

    with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
        ui.label(title).classes("text-lg font-medium")
        if hint:
            ui.label(hint).classes("text-xs opacity-70 -mt-1")

        with ui.row().classes("gap-1 flex-wrap items-center"):
            for label, place in shortcuts():
                ui.button(label, icon="folder",
                          on_click=lambda _, p=place: go(p)).props("dense flat no-caps")

        crumbs = ui.row().classes("items-center gap-1 flex-wrap")
        listing = ui.column().classes("w-full gap-0 h-72 overflow-auto")
        chosen = ui.label().classes("text-xs opacity-70 break-all")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat dense")
            ui.button("Use this folder", icon="check", on_click=lambda: pick()).props("dense")

    def pick() -> None:
        dialog.close()
        on_pick(str(state["path"]))

    def go(path: Path) -> None:
        state["path"] = Path(path).resolve()
        draw()

    def draw() -> None:
        here = state["path"]
        chosen.set_text(str(here))

        crumbs.clear()
        with crumbs:
            parts = [here, *here.parents]
            for part in reversed(parts):
                ui.button(part.name or "/", on_click=lambda _, p=part: go(p)) \
                    .props("dense flat no-caps size=sm")
                ui.label("/").classes("text-xs opacity-40")

        listing.clear()
        with listing:
            if here.parent != here:
                with ui.row().classes("items-center gap-2 w-full py-1 cursor-pointer") \
                        .on("click", lambda _, p=here.parent: go(p)):
                    ui.icon("arrow_upward").classes("opacity-60")
                    ui.label("..").classes("text-sm")
            children = subfolders(here)
            if not children:
                ui.label("No folders in here.").classes("text-xs opacity-60 py-2")
            for child in children:
                with ui.row().classes("items-center gap-2 w-full py-1 cursor-pointer") \
                        .on("click", lambda _, p=child: go(p)):
                    ui.icon("inventory_2" if is_workspace(child) else "folder") \
                        .classes("text-primary" if is_workspace(child) else "opacity-60")
                    ui.label(child.name).classes("text-sm")
                    if is_workspace(child):
                        ui.label("toolkit project").classes("text-xs opacity-60")

    draw()
    dialog.open()


def browse_button(field, *, title: str, hint: str = "", label: str = "Browse…") -> None:
    """A Browse button wired to an input holding a path: opens where the field points, and
    writes the chosen folder back into it."""
    ui.button(label, icon="folder_open",
              on_click=lambda: choose_folder(lambda p: field.set_value(p),
                                             start=field.value or None,
                                             title=title, hint=hint)) \
        .props("dense outline no-caps")
