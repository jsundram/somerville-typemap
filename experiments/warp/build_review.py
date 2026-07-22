# /// script
# requires-python = ">=3.11"
# ///
"""Assemble review.html (the artifact review page) from the loop's outputs.

    uv run experiments/warp/build_review.py

Reads sheet.svg, measure.txt, and README.md (success criteria / taste
rules / results log sections); writes review.html. Deterministic — run it
after every ./iterate.sh, then republish the artifact.
"""

import html
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent

COVERAGE_BAR = 0.35   # keep in sync with README success criteria
SPILL_BAR = 0.005


def md_section(text: str, title: str) -> str:
    """Extract one '## title' section's body from the README."""
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text,
                  re.M | re.S)
    return m.group(1).strip() if m else ""


def md_to_html(md: str) -> str:
    """Tiny renderer: paragraphs, bullet lists, pipe tables. Nothing else."""
    out, bullets, table = [], [], []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()
        if table:
            head, *body = table
            rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                           for r in body)
            out.append("<div class='scroll'><table><thead><tr>"
                       + "".join(f"<th>{c}</th>" for c in head)
                       + f"</tr></thead><tbody>{rows}</tbody></table></div>")
            table.clear()

    def inline(s: str) -> str:
        s = html.escape(s, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        return s

    for line in md.splitlines():
        line = line.rstrip()
        if line.startswith("|"):
            cells = [inline(c.strip()) for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r"-+", c) for c in cells):  # skip |---|
                table.append(cells)
        elif line.startswith("- "):
            if table:
                flush()
            bullets.append(inline(line[2:]))
        elif line:
            flush()
            out.append(f"<p>{inline(line)}</p>")
        else:
            flush()
    flush()
    return "\n".join(out)


def parse_measure(text: str):
    """measure.txt -> (algorithm, [(name, cov, spill)], median_cov, max_spill)."""
    algo = "?"
    rows = []
    for line in text.splitlines():
        if line.startswith("algorithm:"):
            algo = line.split(":", 1)[1].strip()
            continue
        m = re.match(r"(.+?)\s+([\d.]+)%\s+([\d.]+)%$", line)
        if m and m.group(1).strip() not in ("median", "worst", "neighborhood"):
            rows.append((m.group(1).strip(),
                         float(m.group(2)) / 100, float(m.group(3)) / 100))
    covs = sorted(c for _, c, _ in rows)
    med = covs[len(covs) // 2] if covs else 0.0
    max_spill = max((s for _, _, s in rows), default=0.0)
    return algo, rows, med, max_spill


def main():
    svg = (HERE / "sheet.svg").read_text()
    readme = (HERE / "README.md").read_text()
    algo, rows, med, max_spill = parse_measure((HERE / "measure.txt").read_text())

    cov_ok = med >= COVERAGE_BAR
    spill_ok = max_spill <= SPILL_BAR
    verdict = (
        f"<span class='chip {'pass' if cov_ok else 'fail'}'>median coverage "
        f"{med:.1%} <small>/ bar ≥ {COVERAGE_BAR:.0%}</small></span> "
        f"<span class='chip {'pass' if spill_ok else 'fail'}'>max spill "
        f"{max_spill:.1%} <small>/ bar ≤ {SPILL_BAR:.1%}</small></span>")

    metric_rows = "".join(
        f"<tr><td>{html.escape(n)}</td>"
        f"<td class='num'>{c:.1%}</td>"
        f"<td class='num {'bad' if s > SPILL_BAR else ''}'>{s:.1%}</td></tr>"
        for n, c, s in rows)

    sections = "".join(
        f"<section><h2>{t}</h2>{md_to_html(md_section(readme, t))}</section>"
        for t in ("Success criteria", "Taste rules (edit freely)", "Results log"))

    page = f"""<title>Warp hero glyphs — review</title>
<style>
:root {{
  --ground: #f6f6f4; --card: #ffffff; --ink: #1c1f26; --muted: #6b7078;
  --line: #dcdcd6; --accent: #3a5fa0; --pass: #2f7d52; --fail: #b0452f;
  --chip-pass: #e3efe7; --chip-fail: #f6e6e0;
}}
@media (prefers-color-scheme: dark) {{ :root {{
  --ground: #16181d; --card: #1e2127; --ink: #e6e7e4; --muted: #969aa3;
  --line: #33363e; --accent: #8aabdf; --pass: #7fc39a; --fail: #dd9077;
  --chip-pass: #23372b; --chip-fail: #3d2822;
}} }}
:root[data-theme="light"] {{
  --ground: #f6f6f4; --card: #ffffff; --ink: #1c1f26; --muted: #6b7078;
  --line: #dcdcd6; --accent: #3a5fa0; --pass: #2f7d52; --fail: #b0452f;
  --chip-pass: #e3efe7; --chip-fail: #f6e6e0;
}}
:root[data-theme="dark"] {{
  --ground: #16181d; --card: #1e2127; --ink: #e6e7e4; --muted: #969aa3;
  --line: #33363e; --accent: #8aabdf; --pass: #7fc39a; --fail: #dd9077;
  --chip-pass: #23372b; --chip-fail: #3d2822;
}}
body {{
  background: var(--ground); color: var(--ink);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin: 0; padding: 2rem 1.25rem 4rem;
}}
main {{ max-width: 68rem; margin: 0 auto; display: grid; gap: 2rem; }}
header h1 {{
  font-family: "Arial Rounded MT Bold", "Cooper Black", "Chalkboard SE", sans-serif;
  font-size: 2rem; margin: 0 0 .25rem; text-wrap: balance;
}}
header .sub {{ color: var(--muted); }}
header .sub b {{ color: var(--accent); }}
.chips {{ margin-top: .9rem; display: flex; gap: .5rem; flex-wrap: wrap; }}
.chip {{
  border-radius: 999px; padding: .3rem .85rem; font-weight: 600;
  font-size: .9rem;
}}
.chip small {{ font-weight: 400; opacity: .75; }}
.chip.pass {{ background: var(--chip-pass); color: var(--pass); }}
.chip.fail {{ background: var(--chip-fail); color: var(--fail); }}
.sheet {{
  background: #ffffff; border: 1px solid var(--line); border-radius: 6px;
  padding: .5rem;
}}
.sheet svg {{ display: block; width: 100%; height: auto; }}
h2 {{
  font-size: .85rem; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 .75rem;
  border-bottom: 1px solid var(--line); padding-bottom: .4rem;
}}
.scroll {{ overflow-x: auto; }}
table {{
  border-collapse: collapse; width: 100%;
  font: .85rem/1.5 ui-monospace, "SF Mono", Menlo, monospace;
  font-variant-numeric: tabular-nums;
}}
th {{ text-align: left; color: var(--muted); font-weight: 600; }}
th, td {{ padding: .3rem .75rem .3rem 0; border-bottom: 1px solid var(--line); }}
td.num {{ text-align: right; }} th.num {{ text-align: right; }}
td.bad {{ color: var(--fail); font-weight: 700; }}
section p, section li {{ max-width: 65ch; }}
code {{
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: .9em;
  background: var(--card); border: 1px solid var(--line);
  border-radius: 3px; padding: 0 .25em;
}}
footer {{
  border-top: 1px solid var(--line); padding-top: 1rem;
  color: var(--muted); font-size: .9rem; max-width: 65ch;
}}
footer strong {{ color: var(--ink); }}
</style>
<main>
<header>
  <h1>Warp hero glyphs</h1>
  <div class="sub">algorithm <b>{html.escape(algo)}</b> · run {date.today().isoformat()}
   · 19 neighborhoods</div>
  <div class="chips">{verdict}</div>
</header>
<div class="sheet">{svg}</div>
<section>
  <h2>Per-neighborhood metrics</h2>
  <div class="scroll"><table>
    <thead><tr><th>neighborhood</th><th class="num">coverage</th>
    <th class="num">spill</th></tr></thead>
    <tbody>{metric_rows}</tbody>
  </table></div>
</section>
{sections}
<footer>
  <strong>How to steer:</strong> edit the taste rules or bars in
  <code>experiments/warp/README.md</code> (or reply in the Claude session) —
  anything written there is the spec for the next iteration. The loop resumes
  automatically after it sees your edits.
</footer>
</main>
"""
    (HERE / "review.html").write_text(page)
    print(f"wrote {HERE / 'review.html'}")


if __name__ == "__main__":
    main()
