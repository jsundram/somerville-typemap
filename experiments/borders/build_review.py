# /// script
# requires-python = ">=3.11"
# ///
"""Assemble review.html (the artifact review page) from the loop's outputs.

    uv run experiments/borders/build_review.py

Reads out/layers/{L1,L7,L8}*.svg, sheet.svg, measure.txt, and README.md
(goal / bars / results log); writes review.html. Deterministic — rebuild
after every measure+sheet pass, then republish the artifact.
"""

import html
import re
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
LAYERS = ["L1_basemap", "L7_boundaries", "L8_annotations"]
OPACITY = {"L1_basemap": 0.35}


def md_section(text: str, title: str) -> str:
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
            if not all(re.fullmatch(r"-+", c) for c in cells):
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


def svg_inner(path: Path) -> tuple[str, str]:
    """Return (viewBox, inner markup) of an SVG file."""
    text = path.read_text()
    vb = re.search(r'viewBox="([^"]+)"', text).group(1)
    inner = re.sub(r"^.*?<svg[^>]*>", "", text, count=1, flags=re.S)
    inner = re.sub(r"</svg>\s*$", "", inner)
    return vb, inner


def stat_tiles(measure: str) -> str:
    ann = re.search(r"annotated: (\d+%)\s+labeled: (\d+%)", measure)
    warns = measure.count("⚠")
    nothing = re.search(r"\(nothing\)\s+(\d+) runs\s+([\d,]+)px", measure)
    tiles = [("annotated", ann.group(1) if ann else "?"),
             ("labeled", ann.group(2) if ann else "?"),
             ("runs over bar", str(warns)),
             ("unannotated", f"{nothing.group(1)} runs / {nothing.group(2)}px"
              if nothing else "?")]
    return "".join(
        f"<div class='tile'><div class='num'>{v}</div>"
        f"<div class='cap'>{k}</div></div>" for k, v in tiles)


def main():
    readme = (HERE / "README.md").read_text()
    measure = (HERE / "measure.txt").read_text() \
        if (HERE / "measure.txt").exists() else "(run measure.py first)"
    sheet = (HERE / "sheet.svg").read_text() \
        if (HERE / "sheet.svg").exists() else ""
    sheet = re.sub(r'<svg ', '<svg style="max-width:100%;height:auto" ',
                   sheet, count=1)

    vb, _ = svg_inner(ROOT / "out/layers" / f"{LAYERS[0]}.svg")
    groups = []
    for name in LAYERS:
        _, inner = svg_inner(ROOT / "out/layers" / f"{name}.svg")
        op = f' opacity="{OPACITY[name]}"' if name in OPACITY else ""
        groups.append(f'<g id="lyr_{name}"{op}>{inner}</g>')
    map_svg = (f'<svg id="map" xmlns="http://www.w3.org/2000/svg" '
               f'viewBox="{vb}">' + "".join(groups) + "</svg>")

    page = f"""<title>Borders — annotation review</title>
<style>
  :root {{ --fg: #1a1a1a; --muted: #666; --line: #e2e2e2; --bg: #fff;
           --panel: #fafafa; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg: #e8e8e8; --muted: #9a9a9a; --line: #333; --bg: #141414;
             --panel: #1d1d1d; }} }}
  :root[data-theme="dark"] {{ --fg: #e8e8e8; --muted: #9a9a9a; --line: #333;
             --bg: #141414; --panel: #1d1d1d; }}
  :root[data-theme="light"] {{ --fg: #1a1a1a; --muted: #666; --line: #e2e2e2;
             --bg: #fff; --panel: #fafafa; }}
  body {{ font: 15px/1.5 -apple-system, system-ui, sans-serif;
          color: var(--fg); background: var(--bg);
          max-width: 1200px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 36px; }}
  .tiles {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }}
  .tile {{ background: var(--panel); border: 1px solid var(--line);
           border-radius: 8px; padding: 10px 16px; }}
  .tile .num {{ font-size: 20px; font-weight: 600; }}
  .tile .cap {{ font-size: 12px; color: var(--muted); }}
  #viewport {{ border: 1px solid var(--line); border-radius: 8px;
               height: 640px; overflow: hidden; cursor: grab;
               background: #fff; touch-action: none; }}
  #viewport svg {{ display: block; transform-origin: 0 0; }}
  .hint {{ font-size: 12px; color: var(--muted); margin: 6px 0 0; }}
  pre {{ background: var(--panel); border: 1px solid var(--line);
         border-radius: 8px; padding: 12px; overflow-x: auto;
         font-size: 12px; line-height: 1.45; }}
  .scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  th, td {{ border: 1px solid var(--line); padding: 5px 9px;
            text-align: left; vertical-align: top; }}
  th {{ background: var(--panel); }}
  .sheet {{ border: 1px solid var(--line); border-radius: 8px;
            overflow-x: auto; background: #fff; }}
</style>

<h1>Borders — annotation alignment review</h1>
<p class="hint">Basemap at 35% under boundary lines (L7) and their
annotations (L8). Every colored stroke should ride its border; every
border on a real feature should carry its label.</p>
<div class="tiles">{stat_tiles(measure)}</div>

<h2>Map — L1 + L7 + L8</h2>
<div id="viewport">{map_svg}</div>
<p class="hint">drag to pan · wheel/pinch to zoom · double-click to reset</p>

<h2>Worst-aligned runs (closeups)</h2>
<p class="hint">Dark = administrative border; colored dash = annotation
stroke. From sheet.py, worst first.</p>
<div class="sheet">{sheet}</div>

<h2>Metrics</h2>
<pre>{html.escape(measure)}</pre>

<h2>Goal</h2>
{md_to_html(md_section(readme, "Metrics & bars"))}

<h2>Results log</h2>
{md_to_html(md_section(readme, "Results log"))}

<script>
  const vp = document.getElementById('viewport');
  const svg = document.getElementById('map');
  let sc = 0.34, tx = 0, ty = 0, drag = null;
  const apply = () => svg.style.transform =
      `translate(${{tx}}px,${{ty}}px) scale(${{sc}})`;
  const fit = () => {{
    sc = vp.clientWidth / svg.viewBox.baseVal.width;
    svg.style.width = svg.viewBox.baseVal.width + 'px';
    svg.style.height = svg.viewBox.baseVal.height + 'px';
    tx = 0; ty = 0; apply();
  }};
  vp.addEventListener('pointerdown', e => {{
    drag = {{x: e.clientX - tx, y: e.clientY - ty}};
    vp.setPointerCapture(e.pointerId); vp.style.cursor = 'grabbing';
  }});
  vp.addEventListener('pointermove', e => {{
    if (drag) {{ tx = e.clientX - drag.x; ty = e.clientY - drag.y; apply(); }}
  }});
  vp.addEventListener('pointerup', () => {{ drag = null;
    vp.style.cursor = 'grab'; }});
  vp.addEventListener('wheel', e => {{
    e.preventDefault();
    const r = vp.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const f = Math.exp(-e.deltaY * 0.002);
    tx = mx - (mx - tx) * f; ty = my - (my - ty) * f; sc *= f; apply();
  }}, {{passive: false}});
  vp.addEventListener('dblclick', fit);
  fit();
</script>
"""
    (HERE / "review.html").write_text(page)
    print(f"wrote {HERE / 'review.html'} ({len(page) / 1024:.0f}K)")


if __name__ == "__main__":
    main()
