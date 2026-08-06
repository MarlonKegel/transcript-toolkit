"""Per-interview annotated review pages for `toolkit label` — clip boundaries WITH their labels.

Mirrors diags/clip/ (clips AND procedural paragraphs in document order), adding a **Label:** line
under each clip header. Procedural blocks get no label line (procedural paragraphs are never
labeled). `run_label` writes these self-contained HTML pages for the interviews it just processed,
plus an `index.html`; `annotate_labels` re-renders every labeled interview from the deliverables.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...core.reviewdoc import (BACK_LABEL, document, effective_ts, esc, para,
                              write_index)
from ...errors import ToolkitError
from ...project import Project


def label_line(clip_id: str, label: str, overridden: bool) -> str:
    """One clip's label paragraph. Also what the app's edit endpoint splices into a page that
    is already on disk, so the two renderings can never drift apart."""
    flag = ' <span class="editedflag">edited by hand</span>' if overridden else ""
    cls = "label edited" if overridden else "label"
    return (f'<p class="{cls}" data-clip="{esc(clip_id)}"><span class="k">Label:</span> '
            f'<span class="labeltext">{esc(label)}</span>{flag}</p>')


# Served by the app, each label gets a small edit control that saves to label_overrides.csv
# and updates the page on disk. Opened as a plain file (the CLI's `open`), there is nowhere
# to save to, so the script leaves the page exactly as static as it always was.
EDIT_EXTRAS = """
<style>
p.label .editlabel{margin-left:.6em;font-size:.72em;opacity:.55;cursor:pointer}
p.label .editlabel:hover{opacity:1}
p.label .editedflag{font-size:.72em;opacity:.55;font-style:italic;margin-left:.4em}
p.label input.editbox{font:inherit;width:min(38em,80%)}
p.label .editbar button{margin-left:.4em;font-size:.8em}
</style>
<script>
(function () {
  if (location.protocol === "file:") return;
  document.querySelectorAll("p.label[data-clip]").forEach(function (p) {
    var span = p.querySelector(".labeltext");
    var btn = document.createElement("button");
    btn.textContent = "edit"; btn.className = "editlabel";
    btn.title = "Change this label by hand. Your version is kept in label_overrides.csv and the export uses it.";
    btn.onclick = function () {
      var bar = document.createElement("span"); bar.className = "editbar";
      var box = document.createElement("input"); box.className = "editbox";
      box.value = span.textContent;
      var save = document.createElement("button"); save.textContent = "save";
      var cancel = document.createElement("button"); cancel.textContent = "cancel";
      bar.append(box, save, cancel);
      function done() { bar.remove(); span.style.display = ""; btn.style.display = ""; }
      save.onclick = function () {
        fetch("/api/labels/edit", {
          method: "POST",
          headers: {"Content-Type": "application/json", "X-Toolkit-Edit": "1"},
          body: JSON.stringify({clip_id: p.dataset.clip, label: box.value,
                                was: span.textContent})
        }).then(function (r) {
          if (!r.ok) return r.json().then(function (e) { throw (e && e.detail) || r.status; });
          location.reload();                    // the page on disk was updated to match
        }).catch(function (err) { alert("Not saved: " + err); });
      };
      cancel.onclick = done;
      box.onkeydown = function (e) {
        if (e.key === "Enter") save.onclick();
        if (e.key === "Escape") done();
      };
      span.style.display = "none"; btn.style.display = "none";
      p.appendChild(bar); box.focus();
    };
    p.appendChild(btn);
  });
})();
</script>"""


def render_annotated(interview_id: str, paragraphs: pd.DataFrame, clips: pd.DataFrame,
                     label_by_id: dict[str, str], overridden: set[str] | None = None) -> str:
    paragraphs = paragraphs.sort_values("paragraph_idx").reset_index(drop=True)
    # Normalize missing clip_id to None so runs group cleanly (NaN/pd.NA break `==` grouping).
    paragraphs = paragraphs.assign(clip_id=[None if pd.isna(c) else c for c in paragraphs["clip_id"]])
    clips = clips.sort_values("start_paragraph_idx").reset_index(drop=True)

    n_proc = int((paragraphs["clip_id"] == "procedural").sum())
    n_in_clip = int(paragraphs["clip_id"].notna().sum()) - n_proc
    subtitle = (f"<b>{len(clips)}</b> clips · <b>{len(paragraphs)}</b> paragraphs · "
                f"{n_in_clip} in clips · {n_proc} procedural · "
                f"{int(paragraphs['word_count'].sum())} words")

    clip_lookup = {c.clip_id: c for c in clips.itertuples()}
    clip_number = {c.clip_id: i for i, c in enumerate(clips.itertuples(), start=1)}

    body: list[str] = []
    rows = list(paragraphs.itertuples())
    i = 0
    while i < len(rows):
        cid = rows[i].clip_id
        j = i
        while j < len(rows) and rows[j].clip_id == cid:
            j += 1
        block = rows[i:j]
        start_idx = int(block[0].paragraph_idx)
        end_idx = int(block[-1].paragraph_idx)
        words = sum(int(r.word_count) for r in block)
        span = f"paragraph {start_idx}" if start_idx == end_idx else f"paragraphs {start_idx}–{end_idx}"

        if cid == "procedural":
            cls = "proc"
            h2 = esc(f"Procedural — {span} · {len(block)} paragraph(s) · {words} words")
            label_para = ""
        elif cid is None:
            cls = "unassigned"
            h2 = esc(f"Unassigned — {span} · {len(block)} paragraph(s)")
            label_para = ""
        else:
            c = clip_lookup[cid]
            n = clip_number[cid]
            dur = ""
            if c.duration_seconds is not None and not pd.isna(c.duration_seconds):
                dur = f" · {c.duration_seconds / 60:.1f} min"
            cls = "clip"
            h2 = (f"Clip {n} <span class=\"meta\">{esc(span)} · {len(block)} paragraph(s) · "
                  f"{words} words{esc(dur)}</span>")
            label_para = label_line(cid, label_by_id.get(cid, "⟨missing⟩"),
                                    cid in (overridden or ()))

        body.append(f'<section class="{cls}">')
        body.append(f"<h2>{h2}</h2>")
        if label_para:
            body.append(label_para)
        body.extend(para(int(r.paragraph_idx), effective_ts(r), r.speaker_role, r.speech) for r in block)
        body.append("</section>")
        i = j

    body.append(EDIT_EXTRAS)
    return document(interview_id, "\n".join(body), subtitle=subtitle,
                    back=("index.html", BACK_LABEL))


def write_annotated(project: Project, interview_ids: list[str], paras_df: pd.DataFrame,
                    clips_df: pd.DataFrame, label_by_id: dict[str, str]) -> Path:
    """Write diags/label/{interview_id}.html for each interview + an index.html; returns the dir."""
    from ...core import overrides as overrides_mod

    edits, complaints = overrides_mod.overlay(project, clips_df)
    for reason in complaints:
        print(f"⚠ {reason}")
    shown = {**label_by_id, **{cid: lbl for cid, lbl in edits.items() if cid in label_by_id}}
    overridden = set(edits) & set(label_by_id)

    diag_dir = project.diags_dir / "label"
    diag_dir.mkdir(parents=True, exist_ok=True)
    for iid in interview_ids:
        html = render_annotated(iid, paras_df[paras_df["interview_id"] == iid],
                                clips_df[clips_df["interview_id"] == iid], shown,
                                overridden=overridden)
        (diag_dir / f"{iid}.html").write_text(html)
    counts = (clips_df.groupby("interview_id").size().to_dict()
              if "interview_id" in clips_df.columns else {})
    entries = [(p.name, p.stem, f"{counts.get(p.stem, '?')} clips")
               for p in sorted(diag_dir.glob("*.html")) if p.name != "index.html"]
    write_index(diag_dir / "index.html", "Labels — review", entries)
    return diag_dir


def annotate_labels(project: Project) -> None:
    """Re-render every labeled interview's annotated page from the deliverables."""
    labels_path = project.outputs_dir / "labels" / "labels.parquet"
    if not labels_path.exists():
        raise ToolkitError(f"{labels_path} not found. Run `toolkit label` first.")
    clips_path = project.outputs_dir / "clips" / "clips.parquet"
    paras_path = project.outputs_dir / "clips" / "paragraphs_clipped.parquet"
    for path in (clips_path, paras_path):
        if not path.exists():
            raise ToolkitError(f"{path} not found. Run `toolkit clip` first.")

    labels_df = pd.read_parquet(labels_path)
    clips_df = pd.read_parquet(clips_path)
    paras_df = pd.read_parquet(paras_path)
    label_by_id = dict(zip(labels_df["clip_id"], labels_df["label"]))

    ids = sorted(labels_df["interview_id"].unique())
    diag_dir = write_annotated(project, ids, paras_df, clips_df, label_by_id)
    print(f"Wrote {len(ids)} annotated interview(s) -> {diag_dir}/index.html")
