# sample

`toolkit sample` — choose the handful of interviews that `clip --demo` and `label --demo` run
on. Run it once, after `toolkit import`; the choice is remembered.

## Run it

```sh
toolkit sample                       # 5 interviews, picked reproducibly
toolkit sample --n 8                 # a bigger sample
toolkit sample --seed 3              # a different draw
```

Every demo you run from then on covers the whole sample, so a bigger sample costs
proportionally more each time you try a step out. Five is the default for that reason.

## Choosing the interviews yourself

**You do not have to accept a random draw.** Name the interviews you want:

```sh
toolkit sample --interviews ramos_ana,kramer_larry,acemoglu_daron
```

Or name the ones you care about and let the rest be drawn for you — `--n` is the size of the
whole sample, so this gives those two plus three others:

```sh
toolkit sample --n 5 --interviews ramos_ana,kramer_larry
```

Use the interview ids exactly as `toolkit import` printed them (lowercase, underscores — the
filename with its suffixes stripped). An unknown id fails immediately and lists the valid ones,
so a typo can't silently give you a different sample.

In the app this is the **Demo interviews** section of the workspace page: the same choice, with
the interview list in front of you.

This is worth doing when the random five aren't representative — pick a short interview and a
long one, a single-session and a multi-session narrator, or the transcript you know is messiest.
The demo is only useful if it shows you the cases you're actually worried about.

## Why it exists

Every LLM step is demo-first: you run it on a few interviews, review the result, adjust, and only
then spend money on the whole corpus. Fixing the sample means each step demos on the *same*
interviews, so when you compare clip boundaries against the labels they produced, you're looking
at the same material.

Re-running `toolkit sample` replaces the sample. Do that between steps and your earlier demos no
longer correspond to the current one — harmless, but the comparison is lost.

## What it writes

`.toolkit/demo_sample.txt`, one interview id per line. `toolkit status` shows the current sample.

## Which steps use it

| step | demo sample |
|---|---|
| `clip --demo`, `label --demo` | exactly these interviews |
| `topics tag --demo`, `locations tag --demo` | a spread of *clips* drawn from whatever clips exist (`advanced/<step>.yaml` → `demo_n_clips`) |
| `summarize --demo` | its own small draw (`advanced/summarize.yaml` → `demo_n`), since summaries read whole interviews and are the priciest per call |
