"""The project cost report: what this project has actually cost, so far, per step.

The figures come from `steps/cost.spend_report` — the same calculation `toolkit cost` prints, so
the app is a second rendering of it and not a second opinion. Every call a step makes is written
to that step's cache before it is used again, so this is money that has left the account: demos
included, and the calls behind a prompt that has since been rewritten included too.
"""
from __future__ import annotations

from nicegui import ui

from ...errors import ToolkitError
from ...steps.cost import calls
from .. import content
from ..context import CONTEXT
from .common import guard, info

EXPLAINER = (
    "Every call the toolkit makes is recorded in this project before its result is used, so this "
    "is what has actually been billed rather than an estimate.\n\n"
    "It counts everything: the demos, and the calls behind a prompt you have since rewritten. "
    "Re-running a step you have already run costs nothing, because the answers are kept — which "
    "is why the total can stop moving while you work.\n\n"
    "The same figures print in Terminal with `toolkit cost`."
)

TIER_WORD = {"standard": "run now", "batch": "Batch API"}


def report_or_none() -> dict | None:
    from ...steps.cost import spend_report
    try:
        return spend_report(CONTEXT.require_project())
    except ToolkitError as e:
        guard(e)
        return None


def money(usd: float) -> str:
    """Small sums are the normal case here, and rounding a demo to $0.00 makes it look free."""
    if usd and usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:,.2f}"


def step_name(key: str) -> str:
    """The step's own title, so the report names things the way the rest of the app does."""
    base, _, set_name = key.partition(":")
    step = content.BY_SLUG.get(base)
    title = step.title if step else base
    return f"{title} · {set_name}" if set_name else title


def cost_report(report: dict | None = None) -> None:
    """The whole report, for the workspace page."""
    if report is None:
        report = report_or_none()
    if report is None:
        return

    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.label(money(report["total_usd"])).classes("text-2xl font-medium")
            ui.label("billed in this project so far").classes("text-sm opacity-70")
            info(EXPLAINER)
        if not report["steps"]:
            ui.label("Nothing has been run yet, so nothing has been billed.") \
                .classes("text-sm opacity-70")
            return

        rows = [{"step": step_name(e["key"]),
                 "calls": f"{e['calls']:,}",
                 "how": ", ".join(sorted({TIER_WORD[g["tier"]] for g in e["groups"]})) or "—",
                 "models": ", ".join(sorted({g["model"] for g in e["groups"]})),
                 "cost": money(e["usd"])}
                for e in report["steps"]]
        ui.table(columns=[{"name": "step", "label": "Step", "field": "step", "align": "left"},
                          {"name": "models", "label": "Model", "field": "models", "align": "left"},
                          {"name": "how", "label": "Sent as", "field": "how", "align": "left"},
                          {"name": "calls", "label": "Calls", "field": "calls", "align": "right"},
                          {"name": "cost", "label": "Cost", "field": "cost", "align": "right"}],
                 rows=rows, row_key="step").props("dense flat").classes("w-full")

        if report["by_tier"]["standard"]:
            ui.label(f"{money(report['by_tier']['standard'])} of that was sent to run now; the "
                     f"same calls on the Batch API would have been "
                     f"{money(report['sync_if_batched'])}.").classes("text-xs opacity-70")
        for missing in report["unpriced"]:
            ui.label(f"{missing['calls']} calls to {missing['model']} are not counted — the "
                     f"toolkit has no price for that model.").classes("text-xs tk-caution")
        if report["note"]:
            ui.label(report["note"]).classes("text-xs tk-caution whitespace-pre-line")


def step_spend_line(step_key: str) -> None:
    """One line for a step's own page: what this step has cost, and the project total."""
    from ...steps.cost import spent_on

    report = report_or_none()
    if report is None:
        return
    entry = spent_on(report, step_key)
    with ui.row().classes("items-center gap-2"):
        if entry:
            ui.label(f"This step has cost {money(entry['usd'])} so far "
                     f"({calls(entry['calls'])}).").classes("text-xs opacity-70")
        else:
            ui.label("This step has not been billed for anything yet.") \
                .classes("text-xs opacity-70")
        ui.link("project cost report", "/workspace#cost").classes("text-xs")
        info(EXPLAINER)
