import importlib.util
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

import transcript_toolkit.steps.locations.tag as tag_step
from transcript_toolkit.core.llm import build_schema
from transcript_toolkit.errors import ToolkitError
from transcript_toolkit.project import init_project
from transcript_toolkit.state import load_state
from transcript_toolkit.steps.import_ import run_import
from transcript_toolkit.steps.locations import (annotate_locations, run_locations_map,
                                                run_locations_rollup, run_locations_survey,
                                                run_locations_tag)
from transcript_toolkit.steps.locations.tag import (build_instructions, build_location_model,
                                                    clean_entries)

FIXTURES = Path(__file__).parent / "fixtures"


def synthesize_clips(project) -> pd.DataFrame:
    """outputs/clips/clips.parquet from the imported fixture paragraphs: 2-3 contiguous clips
    per interview, mirroring the clip step's schema."""
    paras = pd.read_parquet(project.paragraphs_path)
    rows = []
    for iid, g in paras.groupby("interview_id"):
        g = g.sort_values("paragraph_idx")
        idxs = g["paragraph_idx"].tolist()
        n_clips = 3 if len(idxs) >= 6 else 2
        bounds = [round(i * len(idxs) / n_clips) for i in range(n_clips + 1)]
        for k in range(n_clips):
            lo, hi = idxs[bounds[k]], idxs[bounds[k + 1] - 1]
            sub = g[(g["paragraph_idx"] >= lo) & (g["paragraph_idx"] <= hi)]
            rows.append({"interview_id": iid, "clip_id": f"{iid}_c{k:02d}",
                         "start_paragraph_idx": int(lo), "end_paragraph_idx": int(hi),
                         "n_paragraphs": len(sub), "total_words": int(sub["word_count"].sum()),
                         "start_ts": str(sub.iloc[0]["turn_time_start"]),
                         "end_ts": str(sub.iloc[-1]["turn_time_start"]),
                         "duration_seconds": 60.0})
    df = pd.DataFrame(rows)
    path = project.outputs_dir / "clips" / "clips.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def set_locations_config(project, **overrides):
    """Merge overrides into the locations section of the workspace config.yaml (root wins)."""
    cfg = yaml.safe_load(project.config_path.read_text())
    cfg["locations"] = {**(cfg.get("locations") or {}), **overrides}
    project.config_path.write_text(yaml.safe_dump(cfg))


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = init_project(str(tmp_path / "ws"))
    for name in ["Fake_Alpha_20240101_session1_SYNC.docx",
                 "Fake_Alpha_20240108_session2_SYNC.docx",
                 "Fake, Beta_SYNC.docx"]:
        shutil.copy(FIXTURES / name, project.data_dir / name)
    run_import(project)
    synthesize_clips(project)
    set_locations_config(project, demo_n_clips=4)

    calls = []

    def fake_call_llm(client, model, reasoning, verbosity, schema, instructions,
                      user_content, prompt_cache_key_str, **kwargs):
        calls.append({"instructions": instructions, "user_content": user_content})
        justify = '"justification"' in json.dumps(schema)

        def entry(d):
            return {**d, "justification": f"Justified: {d['place']}."} if justify else d
        parsed = {"countries": [entry({"place": "Prague", "country": "Czech Republic"})],
                  "regions": [entry({"place": "the Balkans", "region": "The Balkans"})]}
        usage = {"input_tokens": 1000, "output_tokens": 50,
                 "reasoning_tokens": 10, "cached_input_tokens": 800}
        return parsed, usage

    monkeypatch.setattr(tag_step, "call_llm", fake_call_llm)
    monkeypatch.setattr(tag_step, "openai_client", lambda root: object())
    project.llm_calls = calls  # test-only attribute
    return project


def wide_path(project):
    return project.outputs_dir / "locations" / "clip_locations.parquet"


# --- tag: demo, gate, deliverables ------------------------------------------------------------

def test_demo_writes_review_only_and_records_state(project):
    df = run_locations_tag(project, demo=True)
    assert len(df) == 4                                   # demo_n_clips set to 4 in the fixture
    assert not wide_path(project).exists()                # no deliverable from a demo
    demo_md = project.diags_dir / "locations" / "demo.md"
    text = demo_md.read_text()
    assert "Czech Republic" in text and "The Balkans" in text
    assert "Justified: Prague." in text                   # demo default: justify on
    demo = load_state(project)["steps"]["locations"]["demo"]
    assert len(demo["units"]) == 4
    assert (project.cache_dir / "locations.jsonl").exists()


def test_full_run_gated_without_demo(project):
    with pytest.raises(ToolkitError, match="No demo run"):
        run_locations_tag(project, yes=True)


def test_justify_on_demo_approves_justify_off_full_run(project):
    run_locations_tag(project, demo=True)                 # justify defaults ON for the demo
    df = run_locations_tag(project, yes=True)             # justify defaults OFF; same fingerprint
    assert wide_path(project).exists()
    assert len(df) == 9                                   # all synthesized clips
    assert list(df.columns) == ["interview_id", "clip_id", "start_paragraph_idx",
                                "end_paragraph_idx", "n_paragraphs", "total_words", "start_ts",
                                "end_ts", "countries", "regions", "n_countries", "n_regions",
                                "has_place", "model", "reasoning_effort"]
    long = pd.read_parquet(project.outputs_dir / "locations" / "clip_locations_long.parquet")
    assert list(long.columns) == ["interview_id", "clip_id", "place", "label", "kind",
                                  "justification"]
    assert set(long["kind"]) == {"country", "region"}
    assert (long["justification"] == "").all()            # full run had justify off
    full = load_state(project)["steps"]["locations"]["full"]
    assert full["n_units"] == 9


def test_prompt_edit_stales_demo(project):
    run_locations_tag(project, demo=True)
    prompt = project.prompts_dir / "tag_locations.md"
    prompt.write_text(prompt.read_text() + "\nNever tag oceans.")
    with pytest.raises(ToolkitError, match="stale"):
        run_locations_tag(project, yes=True)


def test_regions_edit_stales_demo_and_reaches_prompt(project):
    run_locations_tag(project, demo=True)
    regions_path = project.locations_dir / "regions.yaml"
    regions_path.write_text(regions_path.read_text() + "- Atlantis\n")
    with pytest.raises(ToolkitError, match="stale"):      # region list feeds the fingerprint
        run_locations_tag(project, yes=True)
    run_locations_tag(project, demo=True)                 # re-demo with the new vocabulary
    assert "- Atlantis" in project.llm_calls[-1]["instructions"]


def test_skip_demo_check_bypasses_gate(project):
    df = run_locations_tag(project, yes=True, skip_demo_check=True)
    assert len(df) == 9 and wide_path(project).exists()


def test_interview_subset_merges(project):
    run_locations_tag(project, demo=True)
    run_locations_tag(project, yes=True)
    before = pd.read_parquet(wide_path(project))
    run_locations_tag(project, interviews=["fake_beta"], yes=True)
    after = pd.read_parquet(wide_path(project))
    assert len(after) == len(before) == 9                 # merged, not clobbered
    assert set(after["interview_id"]) == set(before["interview_id"])
    full = load_state(project)["steps"]["locations"]["full"]
    assert full["n_units"] == 9                           # subset run did not overwrite record_full


def test_unknown_interview_fails_loud(project):
    run_locations_tag(project, demo=True)
    with pytest.raises(ToolkitError, match="Unknown interview id"):
        run_locations_tag(project, interviews=["nobody"], yes=True)


def test_annotate_rerenders_and_requires_deliverable(project):
    with pytest.raises(ToolkitError, match="locations tag"):
        annotate_locations(project)
    run_locations_tag(project, demo=True)
    run_locations_tag(project, yes=True)
    annotate_locations(project)
    assert (project.diags_dir / "locations" / "locations.md").exists()


def test_batch_transport_fills_cache_and_builds_deliverables(project, monkeypatch):
    run_locations_tag(project, demo=True)

    def fake_run_batch(client, units, batch_dir, **kwargs):
        results = {u["custom_id"]: ({"countries": [{"place": "Rio", "country": "Brazil"}],
                                     "regions": []},
                                    {"input_tokens": 1, "output_tokens": 1,
                                     "reasoning_tokens": 0, "cached_input_tokens": 0})
                   for u in units}
        return results, []

    monkeypatch.setattr(tag_step, "run_batch", fake_run_batch)
    df = run_locations_tag(project, yes=True, batch=True)   # fills cache, then builds deliverables
    assert len(df) == 9 and wide_path(project).exists()
    assert set(df["countries"]) == {"Brazil"}
    records = [json.loads(ln) for ln in
               (project.cache_dir / "locations.jsonl").read_text().splitlines()]
    assert all(r.get("api") == "batch" for r in records[-9:])   # batch records marked


# --- schema / instruction assembly -------------------------------------------------------------

def test_schema_enum_built_from_workspace_regions(project):
    regions = yaml.safe_load((project.locations_dir / "regions.yaml").read_text())
    schema = build_schema(build_location_model(regions), "clip_locations")
    assert schema["schema"]["$defs"]["RegionPlace"]["properties"]["region"]["enum"] == regions
    # justify adds the field to both entry types
    js = build_schema(build_location_model(regions, justify=True), "clip_locations")
    for defn in ("CountryPlace", "RegionPlace"):
        assert "justification" in js["schema"]["$defs"][defn]["properties"]


def test_region_injection_deterministic():
    text = build_instructions("PROMPT", ["A Region", "B Region"], "")
    assert text == "PROMPT\n\n## Acceptable regions\n\n- A Region\n- B Region\n"
    with_addendum = build_instructions("PROMPT", ["A Region"], "JUSTIFY")
    assert with_addendum == "PROMPT\n\n## Acceptable regions\n\n- A Region\n\nJUSTIFY\n"


def test_clean_entries_edge_cases():
    entries = [{"place": "Prague", "country": "Czech Republic"},
               {"place": " prague ", "country": "czech republic"},   # case-insensitive duplicate
               {"place": "Berlin", "country": ""},                    # missing label -> dropped
               {"place": "Kyiv", "country": "Ukraine", "justification": " capital "}]
    out = clean_entries(entries, "country")
    assert out == [{"place": "Prague", "country": "Czech Republic"},
                   {"place": "Kyiv", "country": "Ukraine", "justification": "capital"}]
    assert clean_entries(None, "country") == []
    assert clean_entries([{"place": "x"}], "region") == []


# --- map ----------------------------------------------------------------------------------------

def write_tag_deliverables(project, wide_rows, long_rows):
    out_dir = project.outputs_dir / "locations"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"start_paragraph_idx": 0, "end_paragraph_idx": 1, "n_paragraphs": 2,
            "total_words": 10, "start_ts": "", "end_ts": "", "model": "m", "reasoning_effort": "r"}
    wide = pd.DataFrame([{**meta, **r} for r in wide_rows])
    long = pd.DataFrame(long_rows, columns=["interview_id", "clip_id", "place", "label", "kind",
                                            "justification"])
    wide.to_parquet(out_dir / "clip_locations.parquet", index=False)
    long.to_parquet(out_dir / "clip_locations_long.parquet", index=False)


def test_map_relabel_place_tags_and_none_regions(project):
    set_locations_config(project,
                         relabel={"Czech Republic": "Czechia",
                                  "Israel": "Israel and Palestine",
                                  "Palestine": "Israel and Palestine"},
                         place_tags=["Crimea"])
    write_tag_deliverables(project, [
        {"interview_id": "fake_beta", "clip_id": "c1", "countries": "Czech Republic|Israel|Palestine",
         "regions": "", "n_countries": 3, "n_regions": 0, "has_place": True},
        {"interview_id": "fake_beta", "clip_id": "c2", "countries": "",
         "regions": "Baltics|Polynesia", "n_countries": 0, "n_regions": 2, "has_place": True},
        {"interview_id": "fake_beta", "clip_id": "c3", "countries": "Ukraine",
         "regions": "", "n_countries": 1, "n_regions": 0, "has_place": True},
    ], [
        {"interview_id": "fake_beta", "clip_id": "c1", "place": "Prague",
         "label": "Czech Republic", "kind": "country", "justification": ""},
        {"interview_id": "fake_beta", "clip_id": "c3", "place": "crimea",
         "label": "Ukraine", "kind": "country", "justification": ""},
    ])
    wide = run_locations_map(project)
    by_clip = wide.set_index("clip_id")
    # relabel canonicalizes + merges (Israel + Palestine -> one tag)
    assert by_clip.at["c1", "countries_final"] == "Czechia|Israel and Palestine"
    # region expansion; the NONE-mapped region (Polynesia) is retained but adds no countries
    assert by_clip.at["c2", "countries_from_regions"] == "Estonia|Latvia|Lithuania"
    assert by_clip.at["c2", "regions"] == "Baltics|Polynesia"
    # place tag kept alongside its aggregated country, with `via` provenance
    assert by_clip.at["c3", "countries_final"] == "Ukraine|Crimea"
    long = pd.read_parquet(project.outputs_dir / "locations" / "clip_countries_long.parquet")
    via = long.set_index(["clip_id", "country"])["via"]
    assert via[("c3", "Ukraine")] == "direct" and via[("c3", "Crimea")] == "place"
    assert via[("c2", "Estonia")] == "Baltics"


def test_map_unknown_region_fails_loud(project):
    write_tag_deliverables(project, [
        {"interview_id": "fake_beta", "clip_id": "c1", "countries": "", "regions": "Narnia",
         "n_countries": 0, "n_regions": 1, "has_place": True}], [])
    with pytest.raises(ToolkitError, match="Narnia"):
        run_locations_map(project)


# --- rollup (hybrid, hand-computable) -----------------------------------------------------------

def test_hybrid_rollup_hand_computed(project):
    set_locations_config(project, rollup={"thresholds": [50]})   # one bar -> flat 50%
    out_dir = project.outputs_dir / "locations"
    out_dir.mkdir(parents=True, exist_ok=True)
    s1, s2 = "fake_alpha_20240101_session1", "fake_alpha_20240108_session2"
    # narrator fake_alpha: 4 clips over 2 sessions; fake_beta: 2 clips
    cw = pd.DataFrame([
        {"interview_id": s1, "clip_id": "a1", "regions": "Baltics"},
        {"interview_id": s1, "clip_id": "a2", "regions": ""},
        {"interview_id": s2, "clip_id": "a3", "regions": "Baltics"},
        {"interview_id": s2, "clip_id": "a4", "regions": ""},
        {"interview_id": "fake_beta", "clip_id": "b1", "regions": ""},
        {"interview_id": "fake_beta", "clip_id": "b2", "regions": ""},
    ])
    cl = pd.DataFrame([  # France direct in 2/4 alpha clips (50%) and 1/2 beta clips (50%);
        {"interview_id": s1, "clip_id": "a1", "country": "France", "via": "direct"},
        {"interview_id": s2, "clip_id": "a3", "country": "France", "via": "direct"},
        {"interview_id": s1, "clip_id": "a2", "country": "Brazil", "via": "direct"},  # 1/4 = 25%
        {"interview_id": "fake_beta", "clip_id": "b1", "country": "France", "via": "direct"},
    ])
    cw.to_parquet(out_dir / "clip_countries.parquet", index=False)
    cl.to_parquet(out_dir / "clip_countries_long.parquet", index=False)

    wide = run_locations_rollup(project)
    alpha = wide[wide["interview_key"] == "fake_alpha"].iloc[0]
    beta = wide[wide["interview_key"] == "fake_beta"].iloc[0]
    assert alpha["n_sessions"] == 2 and alpha["n_clips"] == 4
    # France clears its 50% bar; Brazil (25%) does not; Baltics region (2/4 = 50%) is tagged
    # and maps down to Estonia/Latvia/Lithuania, unioned with the direct label
    assert alpha["regions"] == "Baltics"
    assert alpha["labels"] == "Estonia|France|Latvia|Lithuania"
    assert beta["labels"] == "France" and beta["regions"] == ""

    long = pd.read_parquet(out_dir / "interview_locations_long.parquet")
    a = long[long["interview_key"] == "fake_alpha"].set_index("label")
    assert a.at["France", "via"] == "direct"
    assert a.at["France", "n_clips_direct"] == 2 and a.at["France", "pct_clips_direct"] == 50.0
    assert a.at["Estonia", "via"] == "Baltics" and a.at["Estonia", "n_clips_direct"] == 0
    rlong = pd.read_parquet(out_dir / "interview_regions_long.parquet")
    tagged = rlong[rlong["tagged"]]
    assert set(zip(tagged["interview_key"], tagged["region"])) == {("fake_alpha", "Baltics")}


def test_rollup_requires_map_output(project):
    with pytest.raises(ToolkitError, match="locations map"):
        run_locations_rollup(project)


def test_rollup_on_corpus_with_zero_tags(project):
    # Regression: a corpus where no clip mentions any place (live-smoke finding). The empty
    # long table's boolean mask is dtype object; without .astype(bool) pandas treated it as a
    # column selector and rollup crashed with KeyError: 'interview_id'.
    out_dir = project.outputs_dir / "locations"
    out_dir.mkdir(parents=True, exist_ok=True)
    cw = pd.DataFrame([
        {"interview_id": "fake_beta", "clip_id": "b1", "regions": ""},
        {"interview_id": "fake_beta", "clip_id": "b2", "regions": ""},
    ])
    cl = pd.DataFrame(columns=["interview_id", "clip_id", "country", "via"])
    cw.to_parquet(out_dir / "clip_countries.parquet", index=False)
    cl.to_parquet(out_dir / "clip_countries_long.parquet", index=False)

    wide = run_locations_rollup(project)
    assert len(wide) == 1
    assert wide.iloc[0]["labels"] == "" and wide.iloc[0]["n_labels"] == 0
    long = pd.read_parquet(out_dir / "interview_locations_long.parquet")
    assert long.empty


# --- survey: import guard only ------------------------------------------------------------------

def test_survey_import_guard(project):
    if importlib.util.find_spec("spacy") is not None:
        pytest.skip("spaCy installed in this venv; the ImportError hint path cannot be exercised")
    with pytest.raises(ToolkitError, match=r"transcript-toolkit\[survey\]"):
        run_locations_survey(project)
