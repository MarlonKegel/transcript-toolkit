"""`toolkit locations survey` — offline NER overview of the places the corpus spans (optional).

Runs spaCy NER over the imported paragraphs, keeps place entities (GPE/LOC), and sorts every
distinct mention into a coarse bucket — city/neighborhood · subnational region · country ·
supranational region · unresolved — by matching it against a local GeoNames dump. Its only
purpose is to give a human a quick picture of the corpus's geographic spread when tuning the
tagging prompt/regions; deliberately uncurated (no blocklists, no per-corpus overrides).

Heavy deps are optional: `pip install "transcript-toolkit[survey]"` + the spaCy model + the
GeoNames dump (advanced key survey.geonames_dir). NER is idempotent + resumable per interview
(.toolkit/cache/survey/); GeoNames resolution re-runs each time (cheap). Fully offline.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from ...core.config import load_step_config, require
from ...core.reviewdoc import document, esc
from ...core.tables import load_paragraphs
from ...errors import ToolkitError
from ...project import Project

STEP = "locations"


# --- GeoNames level resolution (ported as-is from the working repo; no curation) --------------

LEVEL_RULES = [
    ("continent", {"CONT"}),
    ("region", {"RGN", "RGNE", "RGNH", "RGNL"}),
    ("country (historical)", {"PCLH"}),
    ("country", {"PCLI", "PCL", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR"}),
    ("state/province", {"ADM1", "ADM1H"}),
    ("county/district", {"ADM2", "ADM2H"}),
    ("admin (other)", {"ADM3", "ADM4", "ADM5", "ADMD"}),
    ("city/town", {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC",
                   "PPLG", "PPLL", "PPLS", "STLMT", "PPLF", "PPLR"}),
    ("neighborhood", {"PPLX"}),
]
CODE2LEVEL = {c: lvl for lvl, codes in LEVEL_RULES for c in codes}
COUNTRY_LEVELS = {"country", "country (historical)"}
NO_COUNTRY_LEVELS = {"continent", "region"}

# The four coarse buckets the survey sorts mentions into (+ "unresolved" for GeoNames misses).
BUCKETS = ["city/neighborhood", "subnational region", "country", "supranational region", "unresolved"]


def normalize(text: str) -> str:
    t = text.strip()
    if t.casefold().startswith("the "):
        t = t[4:]
    return t.casefold()


def load_country_names(gn_dir: Path) -> dict[str, str]:
    cc2country = {}
    for line in (gn_dir / "countryInfo.txt").open(encoding="utf-8"):
        if line.startswith("#"):
            continue
        p = line.rstrip("\n").split("\t")
        if len(p) > 4 and p[0]:
            cc2country[p[0]] = p[4]
    return cc2country


def collect_candidates(gn_dir: Path, targets: set[str]) -> dict[str, list[tuple]]:
    """One streaming pass over allCountries; keep (code, class, cc, pop, name, geonameid) per target."""
    cand: dict[str, list[tuple]] = {t: [] for t in targets}
    with (gn_dir / "allCountries.txt").open(encoding="utf-8") as f:
        for line in f:
            p = line.split("\t")
            if len(p) < 15:
                continue
            if p[6] not in ("A", "P", "L"):           # admin / populated place / region only
                continue                               # (drops spots, streets, buildings, islands, ...)
            keys = {p[1].casefold(), p[2].casefold()}
            if p[3]:                                   # match alternatenames too: countries/states use
                keys |= {a.casefold() for a in p[3].split(",")}   # long official names; cities have aliases
            for k in keys & targets:                   # ("New York"->NYC, "Bombay"->Mumbai, "Saigon"->HCMC)
                cand[k].append((p[7], p[6], p[8], int(p[14]) if p[14] else 0, p[1], p[0]))
    return cand


def level_of(code: str, cls: str) -> str:
    return CODE2LEVEL.get(code) or ("region" if cls == "L" else
                                    "admin (other)" if cls == "A" else "city/town")


def resolve(rows: list[tuple], cc2country: dict[str, str]) -> dict:
    """Pick the best GeoNames candidate for one mention -> {level, country, cc, geonameid, population}.

    Generally-valid heuristics only (no per-corpus curation): prefer a country match (a bare name
    usually denotes the country, e.g. Georgia); otherwise take the most populous candidate, but
    prefer a same-name populated place over its eponymous admin unit on a near-tie (within 2x) so
    capitals resolve to the city (Budapest, Paris) rather than the homonymous administrative unit.
    """
    if not rows:
        return {"level": "UNCODED", "country": "", "cc": "", "geonameid": "", "population": 0}
    rows = sorted(rows, key=lambda r: -r[3])           # population desc
    country_cands = [r for r in rows if level_of(r[0], r[1]) in COUNTRY_LEVELS]
    if country_cands:
        top = country_cands[0]
    else:
        top = rows[0]
        if top[1] in ("A", "L"):                       # admin/region on top -> prefer a near-tie city
            for r in rows:
                if r[1] == "P" and r[3] >= 0.5 * top[3]:
                    top = r
                    break

    code, cls, cc, pop, name, gid = top
    level = level_of(code, cls)
    if level in NO_COUNTRY_LEVELS:
        country = ""
    elif level in COUNTRY_LEVELS:
        country = cc2country.get(cc, name)             # country maps to itself
    else:
        country = cc2country.get(cc, cc)               # subnational -> containing country
    return {"level": level, "country": country, "cc": cc, "geonameid": gid, "population": pop}


def bucket(level: str, cc: str) -> str:
    """Coarse survey category for a resolved mention. A GeoNames 'region' carrying a country code
    is subnational (Silicon Valley, Donbas); without one it is supranational (Eastern Europe)."""
    if level in ("city/town", "neighborhood"):
        return "city/neighborhood"
    if level in ("state/province", "county/district", "admin (other)"):
        return "subnational region"
    if level in COUNTRY_LEVELS:
        return "country"
    if level == "continent":
        return "supranational region"
    if level == "region":
        return "subnational region" if cc else "supranational region"
    return "unresolved"


# --- NER over the imported paragraphs ----------------------------------------------------------

def snippet(text: str, start: int, end: int, pad: int = 60) -> str:
    """Window of `text` around [start, end) with the entity wrapped in «»."""
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{text[lo:start]}«{text[start:end]}»{text[end:hi]}{suffix}".replace("\n", " ")


def iter_place_mentions(nlp, items, keep_set):
    """Run `nlp` over (speech, meta) pairs; yield one dict per kept entity (meta + ent fields).
    Single process (n_process=1) keeps one transformer model in memory."""
    for doc, meta in nlp.pipe(((s, m) for s, m in items), as_tuples=True, n_process=1):
        for ent in doc.ents:
            if ent.label_ not in keep_set:
                continue
            yield {
                **meta,
                "ent_text": ent.text,
                "ent_label": ent.label_,
                "start_char": ent.start_char,
                "end_char": ent.end_char,
                "context": snippet(doc.text, ent.start_char, ent.end_char),
            }


def _input_hash(speeches: list[str], model: str, keep_labels: list[str], roles: list[str]) -> str:
    """Hash every input that changes an interview's extracted mentions, so editing the transcript
    or the survey config invalidates that interview's cache and it re-extracts."""
    h = hashlib.sha1()
    for s in speeches:
        h.update(s.encode())
        h.update(b"\x00")
    h.update(model.encode())
    for group in (keep_labels, roles):
        h.update(("|".join(sorted(group))).encode())
    return h.hexdigest()


def run_locations_survey(project: Project) -> None:
    cfg = load_step_config(project, STEP)
    require(cfg, ["survey"], STEP)
    scfg = cfg["survey"]
    for k in ("spacy_model", "place_labels", "speaker_roles"):
        if scfg.get(k) is None:
            raise ToolkitError(f"Missing survey setting {k!r} (advanced/locations.yaml).")
    model = scfg["spacy_model"]

    try:
        import spacy
    except ImportError:
        raise ToolkitError(
            'The locations survey needs spaCy: pip install "transcript-toolkit[survey]", then '
            f"install the model once: python -m spacy download {model}") from None

    if not scfg.get("geonames_dir"):
        raise ToolkitError(
            "survey.geonames_dir is not set (advanced/locations.yaml). Download the GeoNames dump "
            "(allCountries.zip + countryInfo.txt from https://download.geonames.org/export/dump/), "
            "unzip it into a directory, and point survey.geonames_dir at it.")
    gn_dir = Path(scfg["geonames_dir"])
    if not gn_dir.is_absolute():
        gn_dir = project.root / gn_dir
    if not (gn_dir / "allCountries.txt").exists():
        raise ToolkitError(f"GeoNames dump not found in {gn_dir} (need allCountries.txt + "
                           f"countryInfo.txt from https://download.geonames.org/export/dump/).")

    try:
        nlp = spacy.load(model)
    except OSError as e:
        raise ToolkitError(f"Could not load spaCy model {model!r}. Install once:\n"
                           f"    python -m spacy download {model}\n({e})") from e

    paragraphs = load_paragraphs(project)
    roles = list(scfg["speaker_roles"] or [])
    if roles:
        paragraphs = paragraphs[paragraphs["speaker_role"].isin(roles)]
    keep_set = set(scfg["place_labels"])

    cache_dir = project.cache_dir / "survey"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mentions_path = cache_dir / f"mentions_{model}.parquet"
    df = pd.read_parquet(mentions_path) if mentions_path.exists() else pd.DataFrame()
    done_hash = (df.drop_duplicates("interview_id").set_index("interview_id")["input_hash"].to_dict()
                 if not df.empty else {})

    iids = sorted(paragraphs["interview_id"].unique())
    print(f"spaCy model: {model} | keep labels: {sorted(keep_set)} | interviews: {len(iids)}")
    for i, iid in enumerate(iids, 1):
        g = paragraphs[paragraphs["interview_id"] == iid].sort_values("paragraph_idx")
        ihash = _input_hash(list(g["speech"]), model, list(keep_set), roles)
        if done_hash.get(iid) == ihash:
            print(f"  [{i}/{len(iids)}] {iid}: up to date, skip")
            continue
        items = ((r.speech, {"interview_id": iid, "paragraph_idx": int(r.paragraph_idx),
                             "speaker_role": r.speaker_role}) for r in g.itertuples())
        mentions = [{**rec, "input_hash": ihash} for rec in iter_place_mentions(nlp, items, keep_set)]
        # Always persist at least one row carrying input_hash so a zero-mention interview is still
        # remembered as done (a sentinel with empty ent_text, dropped below) and not re-run.
        rows = mentions or [{"interview_id": iid, "paragraph_idx": -1, "speaker_role": "",
                             "ent_text": "", "ent_label": "", "start_char": -1, "end_char": -1,
                             "context": "", "input_hash": ihash}]
        if not df.empty:
            df = df[df["interview_id"] != iid]
        df = pd.concat([df, pd.DataFrame.from_records(rows)], ignore_index=True)
        df.to_parquet(mentions_path, index=False)
        done_hash[iid] = ihash
        print(f"  [{i}/{len(iids)}] {iid}: {len(mentions)} mentions ({len(g)} paragraphs)")

    mentions = df[df["ent_text"].astype(str) != ""]      # drop zero-mention sentinel rows
    if mentions.empty:
        raise ToolkitError("No place mentions extracted; nothing to survey.")

    survey = _build_survey(mentions, gn_dir)
    out_dir = project.diags_dir / "locations" / "survey"
    out_dir.mkdir(parents=True, exist_ok=True)
    survey.to_csv(out_dir / "survey.csv", index=False)
    _write_html(survey, out_dir / "survey.html", model)
    print(f"\nWrote {len(survey)} distinct mentions -> {out_dir / 'survey.csv'} + survey.html")
    print("\nBy bucket (distinct mentions):")
    print(survey["bucket"].value_counts().reindex(BUCKETS).to_string())


def _build_survey(mentions: pd.DataFrame, gn_dir: Path) -> pd.DataFrame:
    """Distinct mentions -> bucketed table, ordered by bucket then frequency."""
    freq = (mentions.groupby("ent_text")
            .agg(frequency=("interview_id", "size"), n_interviews=("interview_id", "nunique"))
            .reset_index())
    freq["norm"] = freq["ent_text"].map(normalize)

    cc2country = load_country_names(gn_dir)
    print(f"\nResolving {len(freq)} distinct mentions against GeoNames ...")
    cand = collect_candidates(gn_dir, set(freq["norm"]))
    res = pd.DataFrame([resolve(cand.get(n, []), cc2country) for n in freq["norm"]], index=freq.index)

    out = freq.join(res)
    out["bucket"] = [bucket(lvl, cc) for lvl, cc in zip(out["level"], out["cc"])]
    out["population"] = pd.to_numeric(out["population"], errors="coerce").astype("Int64")
    out["geonameid"] = out["geonameid"].astype(str)
    out["bucket"] = pd.Categorical(out["bucket"], categories=BUCKETS, ordered=True)
    out = out.sort_values(["bucket", "frequency", "ent_text"], ascending=[True, False, True])
    return out[["ent_text", "bucket", "level", "country", "frequency", "n_interviews",
                "geonameid", "population"]]


def _write_html(survey: pd.DataFrame, path: Path, model: str) -> None:
    subtitle = (f"spaCy <code>{esc(model)}</code> NER + GeoNames level lookup; uncurated — a rough "
                f"map of the corpus's geographic spread, not a deliverable.")
    counts = survey["bucket"].value_counts().reindex(BUCKETS)
    body = ["<h2>Distinct mentions by bucket</h2>", '<ul class="index">']
    body += [f"<li><b>{esc(b)}:</b> {int(counts[b] or 0)}</li>" for b in BUCKETS]
    body.append("</ul>")
    for b in BUCKETS:
        sub = survey[survey["bucket"] == b]
        if sub.empty:
            continue
        body.append(f"<h2>{esc(b)} <span class=\"meta\">top 25 of {len(sub)}</span></h2>")
        body.append("<table><thead><tr><th>mention</th><th>level</th><th>country</th>"
                    '<th class="num">mentions</th><th class="num">interviews</th></tr></thead><tbody>')
        for r in sub.head(25).itertuples():
            body.append(f"<tr><td>{esc(r.ent_text)}</td><td>{esc(r.level)}</td>"
                        f'<td>{esc(r.country)}</td><td class="num">{r.frequency}</td>'
                        f'<td class="num">{r.n_interviews}</td></tr>')
        body.append("</tbody></table>")
    path.write_text(document(f"Corpus location survey — {len(survey)} distinct mentions",
                             "\n".join(body), subtitle=subtitle))
