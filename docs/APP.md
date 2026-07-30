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

That creates **Transcript Toolkit** in your Applications folder — the one in Finder's sidebar.
Open it, and drag it to your Dock if you want it there. From then on, double-clicking it is how
you start.

On a Mac where you are not allowed to write to `/Applications` (some managed machines), it goes
into your own `~/Applications` instead, which is *not* the Applications in Finder's sidebar. The
command tells you which one it used and how to get there. Either way, Command-Space and typing
the name finds it.

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

**Quit it when you are done** — the gear in the top right corner → Quit the toolkit. Also do that
after installing an update: the copy that is already running keeps using the old version until
you restart it.

## Finding your way around

The bar across the top has three things in it. On the **left**, the toolkit's icon and the
version you are running; clicking the icon takes you to the list of all your projects. In the
**middle**, the project that is open. On the **right**, the gear, which opens Settings from
wherever you are.

- **Home** (the icon) is every project on this Mac, what stage each one has reached, and the
  place to start a new one.
- **Workspace** is the open project: what to do next, its transcripts, the interviews the demos
  run on, and the pipeline.
- Then **one page per step**, and **Export**.

Every page that can run something ends with a **Terminal Viewer**. Inside it is the command
being run and its output, exactly as Terminal would show it — the app is a window onto the
command-line tool this documentation describes, and that panel is the tool itself working. You
never have to read it. It is there so you can see what is happening, and so you can copy a
command out and run it yourself if you ever want to.

While something is running, its own state — how far it has got, and a Stop button — appears
directly under the button you pressed, wherever on the page that is. When it finishes it folds
back to a single line with a tick, so a page you have worked through does not fill up with
panels about things that are over.

## Working through a project

The workspace page always names one next thing to do, and the pages follow the same order.

1. **Workspace** — paste your OpenAI key, drop the `.docx` files in, import them, and pick the
   interviews the demos will run on. Some things worth knowing:

   - **You name the project, not its folder.** "Anderson Family Oral History" gets the folder
     `anderson-family-oral-history`; Home shows you which folder before it makes it. **Browse**
     opens a folder picker, so you never have to know or type a path — though you still can.
   - **One list of transcripts**, showing every `.docx` in the project, whose interview it is,
     how many paragraphs were read out of it, and whether it has been imported yet. A
     drag-and-drop that half worked is visible here rather than something you find out about
     three steps later. On a big collection the list scrolls inside itself, so what comes after
     it is still on screen.
   - **How transcripts are read** — which speaker labels are the interviewer, and which endings
     to strip off a filename — is folded up under that list, because it is the one thing you may
     have to correct before importing again.
   - **Pick the sample of interviews for demos**, once: every step's demo uses the same few, so
     what you read after the clip demo and after the label demo is about the same people. Say
     how many first, then either let them be drawn or choose them yourself — the messy
     transcript, the multi-session narrator. Between 3 and 10; 5 is the usual number, and a
     bigger sample makes every demo proportionally more expensive. Afterwards the interviews
     that were picked are listed, and you can take one out, add a particular one, or add a few
     more at random.

2. **Each step in turn** — clip, label, summarize, topics, locations. Every one is the same
   three moves:

   1. **Try it** on the demo interviews. Nothing is saved to the project and it costs a small
      fraction of the whole collection.
   2. **Read what came out.** The step writes review pages; the page says what to look for in
      them. They open in a tab of their own, and each interview has a link back to the list.
   3. **Then one of these** — change the prompt or a setting and try it again, or run it on
      everything.

   Running it on everything is not offered until the demo has been run, because the toolkit
   refuses it anyway: a full run needs a demo it recognises behind it. Change a prompt, a model
   or a setting and it will ask for a fresh demo, because the old one no longer tells you what
   you would get.

   **A button that would do nothing is greyed out and says so.** Once a step has run over
   everything and nothing that would change the answer has been edited since, running it again
   would send the same calls, get the same answers back out of the cache, and write the same
   files. Hover it and it says that, and what to change to get a different result. Change
   anything — the prompt, the model, a setting, the topic list — and it comes back by itself.
   So do the things that stay useful: *Rebuild these pages* is never greyed out, and neither is
   the comparison, which is meant to be run again with different numbers. Two cases deliberately
   keep the button live: results you have deleted (re-running puts them back, and the calls are
   already paid for), and a collection that has grown since the last full run — then it says
   there is more to do, and running it again does only the new part.

   **Topics** needs a topic list first. Write one in the app — one row per topic, a name and a
   description of what belongs under it — or upload a spreadsheet you already have. What you
   type is kept as you go, and the first time you save it asks what to call the list. The
   description is the only thing the model reads when deciding whether a clip belongs to a
   topic, so it is worth saying what does *not* count as well as what does.

   You can have **more than one topic list**, and each gets a tab of its own, with a tab at the
   end that adds another. Two lists are two pieces of work: separate demos, separate results, and
   their own prompt, model and thinking effort — so a fine-grained list can run on a stronger
   model than a coarse one without either dictating the other. A new list starts on the shared
   prompt; *Give this list its own prompt* is what splits it off. Whichever list you uploaded is
   editable in the same table you would have typed it into, and an Excel file stays an Excel
   file.

   **Locations** has a vocabulary of its own in the same place: *The regions the model may use*.
   It is a strict list — the model cannot answer with anything that is not on it — so it is the
   first thing to change when the region tags are wrong. Saving also says which of those regions
   the country mapping has no entry for, because *Expand regions into countries* stops at one it
   does not know.

   **Topics and Locations have two more moves after that**, because tagging clips is not the
   same as tagging interviews. See below.

3. **From clip tags to interview tags** — on Topics and on Locations, once the whole collection
   is tagged. A clip is what the model reads; a catalogue entry is about an interview. So the
   tags have to move up, and that needs a threshold: how much of an interview has to be about
   something before it is one of that interview's subjects.

   - **Decide how to go from clip tags to interview tags** writes a page with a panel per method,
     each drawing what that way of deciding would tag: one bar per topic, showing how many
     interviews it would reach and the threshold it had to clear. The two binned methods are
     drawn as a grid — one row per number of bins, one column per range — so both can be read at
     once. Whatever your saved results were rolled up with is marked; a rule you have set but not
     yet applied is not, because it has not happened yet. Nothing is sent to OpenAI, so compare
     as often as you like. *What to compare* changes what is drawn.
   - **Roll up to interview tags** is where you set the rule and apply it — one move, because
     they are one decision. Two numbers do the work: how many bins, and the lowest and highest
     threshold. The recommended method gives rarer topics a lower threshold; one threshold for
     everything sounds simpler but buries exactly the topics worth finding. The other methods
     are behind *Use a different method*. Rolling up is free and instant, so changing your mind
     costs a re-run and nothing else.

   Locations works the same way, with one wrinkle: regions are rolled up as regions and only then
   expanded into their countries, so a country becomes an interview's place through a region only
   when the region itself is what that interview is about.

4. **Export** — one Excel file with everything produced so far. Steps that have not run are
   simply left out, so exporting early is fine; run it again later and it will have more in it.

The **project cost report** on the workspace page is what the project has actually cost, per step
and in total. It counts every call ever made in it, demos included, so it is money that has left
the account rather than an estimate. Every step page carries its own share of it beside the
heading, in the same place each time — what something has already cost is asked before deciding
to spend more. (In Terminal: `toolkit cost`.)

At the foot of each step page, **Extra tools** holds the things that are not part of a normal
run: rebuilding review pages from results you already have, and seeing how a long interview will
be divided up before it is sent. Buttons that read something a step has not produced yet are
greyed out, and say what is missing when you hover them.

### Transcripts that were never SYNC'd

The Summarize page has one section no other page has, folded away until you open it:
**Transcripts that were never SYNC'd**. A SYNC'd transcript carries a timestamp on every
paragraph, and that is what lets the toolkit cut it into clips — which is what labels, topics and
places are all attached to. A summary is the exception: it is made from the interview as a whole,
so it needs no times at all.

Drop those files there and they are kept in a folder of their own, out of the collection. Read
them in, try it on a couple, read what came back, then summarize them all — the same three moves,
with a demo of their own. Their summaries go into the same file as the rest, and the export's
Interviews tab gains a **Transcript** column saying which is which: those rows have a summary and
no tags, and the column is what says that is a fact about the transcript rather than work left
undone. (In Terminal: `toolkit import --unsynced`, then `toolkit summarize --unsynced`.)

## Changing what a step does

Two things on every step page change what comes back, and they are on that step's own page
rather than behind the gear:

- **The prompt for this step** — the instructions sent with every call. Rewording them changes
  what comes back. It is the project's own copy, so an edit here changes nothing in any other
  project, and *Put the original back* restores the one the toolkit ships with.
- **Settings for this step** — which model does the work, how much thinking it does, and
  whatever else belongs to that step alone. How clip tags become interview tags is *not* here:
  it belongs to the rollup, which is further down, next to the comparison that informs it.

Labelling also takes **house rules**: a short set of project decisions added to the end of the
prompt — how a name is spelled, what to call something, what never to abbreviate. Write them in
the app; they are saved as a file in the project like everything else.

Each setting is shown with the explanation written beside it in the project's `config.yaml`. If
you reword a comment in that file, the app says the new wording: there is one description of a
setting, and the file is where it lives. Saving writes back into `config.yaml` itself, comments
and all, so a project stays a folder you can open in TextEdit.

Saving either one makes that step's demo out of date, which is the point — try it again and read
the result before running the whole collection.

## What it costs, and when it asks

Nothing is spent without a question first. When you start a full run, the step works out how
many calls it needs and how many it already has cached, then asks — in the app, with buttons:

- **Run now** — results in this session.
- **Use the Batch API** — half the price, but up to a day.
- **Cancel**.

Both prices are shown, and the `i` beside the buttons explains what you are choosing between.
The figures are worked out by the step itself, not by the app, so what you see is what will
actually be spent. Clipping has no Batch option — it asks a plain yes or no.

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

**The gear in the top right corner** opens Settings, from any page. It holds only what is about
the whole project or the installation — a setting that belongs to one step is on that step's page:

- the project's name
- which version you have, whether a newer one exists, and **Update to the most recent
  version** — then quit the app and open it again, because the copy already running keeps
  using the old version until you do
- the button that rebuilds the desktop app
- where the project's files are, and a button that shows the folder in Finder
- **Delete this project**, which asks you to type DELETE and tells you how many transcripts and
  results go with it. On a Mac it moves the folder to the Trash, so a wrong answer is
  recoverable.
- **Quit the toolkit**.

## If your project folder moves or disappears

Renaming a project folder in Finder, moving it to another disk, or throwing it away are all
ordinary things to do, and nothing warns Finder that the app has it open. When the toolkit next
looks and the folder is not there, it closes the project and asks on the workspace page:

- **I moved or renamed it** — point it at the folder's new home and everything carries on. The
  project is intact; only its path changed.
- **I deleted it** — the toolkit forgets it and you are back at a clean start.

Neither answer loses anything the toolkit was holding.
