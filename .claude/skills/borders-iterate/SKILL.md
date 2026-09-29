---
name: borders-iterate
description: Run one iteration of the border-annotation alignment loop (experiments/borders) — measure, fix the worst mismatch or missed label, re-render, log results, republish the review artifact. Designed to be driven by /loop.
---

# One iteration of the borders loop

The experiment: every neighborhood-border stroke that rides a real
basemap feature (street, bike path, rail line, water) must carry that
feature's annotation for its full extent; no annotation may sit where
it doesn't track a border. `experiments/borders/README.md` is the
**live spec** — bars, gotchas, and the results log; the user steers by
editing it between iterations.

## Procedure

1. **Re-read `experiments/borders/README.md` in full.** Bars and
   results-log verdicts may have changed since the last iteration —
   user edits there are steering input and override anything you
   remember. Also check for new user messages in the session.

2. **Measure the current state.**
   ```sh
   uv run render_map.py                        # → out/borders_debug.json
   uv run experiments/borders/measure.py       # → measure.txt
   uv run experiments/borders/sheet.py         # → sheet.svg
   ```

3. **Pick ONE focused target** — the thing the metrics + closeups say
   is worst, roughly in priority order:
   - a *missed* annotation: a "(nothing)" run that visibly rides a
     basemap street/path/rail (compare against L1 in the review map, or
     build detection into measure.py — that tooling gap is itself a
     valid iteration);
   - a *short* annotation: labeled for less than the border's true
     extent along that feature;
   - a *stray/misaligned* stroke: mean_dev over bar that isn't an
     accepted dual-carriageway offset (see README results log).

   Fix via `draw_run` thresholds (`mean_cap`, `slack`, kept-ratio) in
   render_map.py, border classification in typemap/borders.py, or
   measurement tooling — one focused change per iteration so the
   results log stays interpretable. Respect the CLAUDE.md data gotchas
   (culverted streams, GLX exclusion, dual carriageways).

4. **Re-render + re-measure** (same commands as step 2). Verify the fix
   moved its number without regressing others — diff against the
   previous measure.txt.

5. **Judge visually.** Rebuild and read the review page image, or
   screenshot the relevant map area with headless Chrome. Never declare
   a visual change done from numbers alone.

6. **Log.** Append a row to the README results log: date, change,
   coverage, worst mean dev, verdict note. Never rewrite old rows.

7. **Publish.** Run `uv run experiments/borders/build_review.py`, then
   republish `experiments/borders/review.html` with the Artifact tool —
   favicon `🧭`, and pass
   `url: https://claude.ai/code/artifact/74a0ad2a-ba8d-4bd9-b085-8adbcf89f320`
   so the URL stays stable across sessions. Label = short change name
   (e.g. `rail-cap-18`).

8. **Wait for the user's verdict — every time you need feedback or
   direction.** After publishing, stop and ask in the terminal via
   AskUserQuestion: state the one-line result (metric deltas + your
   read of the sheet) and the artifact URL, and offer options like
   *continue as planned (say what that is)* / *adjust <specific knob>*
   / *stop the loop*. Fold the answer into the README (bar change or
   verdict note) so the steering survives the session.

   The user has granted iteration-level autonomy for mechanical
   progress: if an iteration's result is unambiguous (fix landed, no
   regressions, no taste call involved) you may proceed to the next
   iteration after publishing, without asking. Ask whenever a change
   involves judgment (is this dual-carriageway offset acceptable? is
   this border "really" on the feature?), when metrics regress, or
   every ~3 iterations at minimum so drift is caught early.

## Loop wiring

Driven by `/loop /borders-iterate` (dynamic self-paced). When pausing
for the user (step 8), schedule a ScheduleWakeup (~1800 s) only as a
fallback heartbeat; on such a wakeup, re-check README.md for edits and
re-ask rather than proceeding unreviewed. When continuing autonomously,
proceed directly — don't schedule wakeups between back-to-back
iterations. Stop the loop (`stop: true`) when the user says stop, or
when the two zero-bars are met **and** the user has signed off.
