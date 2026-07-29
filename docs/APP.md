# The app

Everything the toolkit does, in a window instead of a terminal. It runs on your own Mac —
nothing is uploaded anywhere, and there is no account to sign into. Behind the window it runs
exactly the same commands this documentation describes, and shows you each one as it goes, so
what you learn here still applies if you ever want to type them yourself.

## Starting it

Once, after installing the toolkit (see [SETUP.md](SETUP.md) steps 1–3):

```sh
toolkit app --install-launcher
```

That creates **Transcript Toolkit** in your Applications folder. Open it, and drag it to your
Dock if you want it there. From then on, double-clicking it is how you start.

macOS may ask once whether the app can access files in your Documents folder — say yes, that
is where your projects live. It only asks again if the app is rebuilt.

You can also start it from a terminal, which is useful if something goes wrong and you want to
see the messages:

```sh
toolkit app
```

## How it behaves

**It keeps running when you close the window.** That is deliberate: a run over a whole
collection takes hours, and closing a browser tab should not throw that away. Come back to the
tab later — or open the app again — and you will find the run still going, with its output
where you left it.

**One thing runs at a time.** If a step is already going, the app says so rather than starting
a second one. Batch API runs are the awkward case: they can take up to a day, and they hold the
slot. Stopping one is safe (see below), and re-running the step afterwards picks the batch back
up without paying twice.

**Stopping is always safe.** Every call that has finished is saved. Stop a run halfway and run
it again tomorrow, and it carries on from where it stopped rather than starting over.

**Quit it when you are done** — Settings → Quit the toolkit. Also do that after installing an
update: the copy that is already running keeps using the old version until you restart it.

**The Terminal panel** under a run is folded away until you open it. Inside is the command
being run and its output, exactly as Terminal would show it — the app is a window onto the
command-line tool this documentation describes, and that panel is the tool itself working. You
never have to open it. It is there so you can see what is happening, and so you can copy a
command out and run it yourself if you ever want to. Above it, one line always shows the last
thing the run said.

## Working through a project

The dashboard always names one next thing to do, and the pages follow the same order.

1. **Workspace** — make a project (a folder holding one collection of transcripts and
   everything made from them), paste your OpenAI key, drop the `.docx` files in, and import
   them. Then choose the interviews the demos will run on. Four things worth knowing:

   - **Browse** opens a folder picker, so you never have to know or type a path — though you
     still can.
   - **You name the project, not its folder.** "Anderson Family Oral History" gets the folder
     `anderson-family-oral-history`; the page shows you which folder before it makes it.
   - The transcript list shows every `.docx` in the project and whether it has been imported
     yet, so a drag-and-drop that half worked is visible rather than something you find out
     about three steps later.
   - **Demo interviews** are chosen here, once, and every step's demo uses them. Take the
     random five, or pick the ones you are actually worried about — the messy transcript, the
     multi-session narrator — and let the rest be drawn. Five is the default; a bigger sample
     makes every demo proportionally more expensive.

2. **Each step in turn** — clip, label, summarize, topics, locations. Every one works the same
   way: run the demo first, open the review pages it writes and read them, then run the whole
   collection. The toolkit refuses a full run until a demo it recognises has been done, and if
   you change a prompt or a model it will ask for a fresh demo, because the old one no longer
   tells you what you would get.

   **Topics** needs a topic list first. Write one in the app — one row per topic, a name and a
   description of what belongs under it — or upload a spreadsheet you already have. What you
   type is kept as you go, and the first time you save it asks what to call the list. The
   description is the only thing the model reads when deciding whether a clip belongs to a
   topic, so it is worth saying what does *not* count as well as what does.

3. **Export** — one Excel file with everything produced so far. Steps that have not run are
   simply left out, so exporting early is fine; run it again later and it will have more in it.

Each step page has an **Advanced** section holding the things that explain how the step works —
how a long interview is divided up before it is sent, for instance. Nothing in there is needed
to run anything. Buttons that read something a step has not produced yet are greyed out, and
say what is missing when you hover them.

## What it costs, and when it asks

Nothing is spent without a question first. When you start a full run, the step works out how
many calls it needs and how many it already has cached, then asks — in the app, with buttons:

- **Run now** — results in this session.
- **Use the Batch API** — half the price, but up to a day.
- **Cancel**.

Both prices are shown. They are worked out by the step itself, not by the app, so what you see
is what will actually be spent.

Demos do not ask: they are small on purpose, usually a few cents.

## When something goes wrong

The app shows the toolkit's own message, which says what to fix. Two of them come with a button
that does the fixing:

- *"No demo sample drawn yet"* — the demo needs a handful of interviews chosen to run on; the
  chooser appears on the step page as well as on the workspace page.
- *"No demo run recorded"* / *"the demo is stale"* — the demo-first rule, above.

Anything else: read the message, and see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

If the app itself will not start, the messages from the last launch are in
`~/Library/Logs/transcript-toolkit/launch.log`. If it says the port is in use by another
program, start it somewhere else and make that permanent:

```sh
toolkit app --install-launcher --port 8378
```

## Settings

The Settings page holds the installation-wide things: which version you have and whether a
newer one exists, the button that rebuilds the desktop app, and a plain text editor for the
current project's `config.yaml`. That file's comments explain every setting; the editor will
refuse to save something that is not valid YAML rather than leave you with a broken project.

Changing a model or a prompt there makes the demos stale on purpose — the next full run will
ask you to look at a fresh demo first.
