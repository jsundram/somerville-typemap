---
name: warp-iterate
description: Run one iteration of the warped-hero-glyphs loop (experiments/warp) — read the README spec, implement/tune an algorithm, render+measure, log results, republish the review artifact. Designed to be driven by /loop.
---

# One iteration of the warp loop

The experiment: cram each neighborhood name into its polygon, letters
individually warped, rainbow-map style. `experiments/warp/README.md` is
the **live spec** — the user steers by editing it between iterations.

## Procedure

1. **Re-read `experiments/warp/README.md` in full.** Bars, taste rules,
   per-shape notes, and results-log verdicts may have changed since last
   iteration — user edits there are steering input and override anything
   you remember. Also check for new user messages in the session.

2. **Pick the next move.** Roughly in order of ambition (see README
   "Candidate algorithms"): implement per-line envelope stretch
   (fontTools glyph outlines — add `fonttools` to `render_sheet.py`'s
   PEP-723 deps; the hero face is Arial Rounded MT Bold, on macOS at
   `/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf`), then
   tune it, then quad-strip FFD for bent shapes (Hillside, Ball Square).
   One focused change per iteration — algorithm, parameter, or per-shape
   fix — so the results log stays interpretable.

3. **Implement** in `experiments/warp/render_sheet.py`'s `ALGORITHMS`
   dict (new entry or tune an existing one). Keep determinism: same
   input → same output, < 5 s for all 19 shapes.

4. **Run** `experiments/warp/iterate.sh <algo>` — renders, rasterizes
   with headless Chrome, measures. Table prints and lands in
   `measure.txt`.

5. **Judge.** Read `sheet.png` (the image, visually) plus the table.
   Check the README's legibility criteria: reading order intact,
   per-glyph x/y scale ratio within bounds, no collisions, letters still
   look like the typeface. Compare against the previous results-log row.

6. **Log.** Append a row to the README's results log: date, algorithm,
   median coverage, max spill, and a verdict note (ship it / too
   distorted / try X). Never rewrite old rows.

7. **Publish.** Run `uv run experiments/warp/build_review.py`, then
   republish `experiments/warp/review.html` with the Artifact tool —
   favicon `🌈`, and pass
   `url: https://claude.ai/code/artifact/c2665e96-3225-4a9b-be4e-2df2ce2c366d`
   so the URL stays stable across sessions. Label = short run name
   (e.g. `envelope-v2`).

8. **Wait for the user's verdict — every iteration.** After publishing,
   ALWAYS stop and ask in the terminal via AskUserQuestion before doing
   anything else: state the one-line result (metric deltas + your own
   read of the sheet) and the artifact URL, and offer options like
   *continue as I planned (say what that is)* / *adjust <specific
   knob>* / *stop the loop*. Do not start the next iteration, schedule
   a wakeup, or touch code until they answer. Fold their answer into
   the README (taste rule, bar change, or verdict note on the log row)
   so the steering survives the session.

   Exception: the user may explicitly grant autonomy ("run N iterations
   without asking", "go until coverage plateaus") — then skip the ask
   until that grant is used up, and note the grant in the results-log
   verdict so the next session knows.

## Loop wiring

Driven by `/loop /warp-iterate` (dynamic self-paced). The
AskUserQuestion in step 8 is the pacing mechanism — the loop is
human-clocked by default. Schedule a ScheduleWakeup (~1800 s) only as a
fallback heartbeat in case the question goes unanswered; on such a
wakeup, re-check README.md for edits (`git diff` / mtime) and re-ask
rather than proceeding unreviewed. Stop the loop (`stop: true`) when
the user says stop, or when bars are met **and** the user has signed
off on taste.
