# /// script
# requires-python = ">=3.11"
# ///
"""Assemble review.html (the artifact review page) from the loop's outputs.

    uv run experiments/borders/build_review.py

Reads out/layers/{L1,L7,L8}*.svg, out/borders_debug.json (closeup cells
via sheet.render_cells), measure.txt, and README.md (goal / bars /
results log); writes review.html. Deterministic — rebuild after every
measure+sheet pass, then republish the artifact.
"""

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from sheet import render_cells  # noqa: E402

LAYERS = ["L1_basemap", "L7_boundaries", "L8_annotations"]
LAYER_LABEL = {"L1_basemap": "basemap", "L7_boundaries": "boundaries (L7)",
               "L8_annotations": "annotations (L8)"}
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
    miss = re.search(r"missed annotations.*?\(([\d,]+)px\):", measure)
    tiles = [("annotated", ann.group(1) if ann else "?"),
             ("labeled", ann.group(2) if ann else "?"),
             ("runs over bar", str(warns)),
             ("unannotated", f"{nothing.group(1)} runs / {nothing.group(2)}px"
              if nothing else "?"),
             ("missed (feature ≥60%)", f"{miss.group(1)}px" if miss else "0px")]
    return "".join(
        f"<div class='tile'><div class='num'>{v}</div>"
        f"<div class='cap'>{k}</div></div>" for k, v in tiles)


def main():
    readme = (HERE / "README.md").read_text()
    measure = (HERE / "measure.txt").read_text() \
        if (HERE / "measure.txt").exists() else "(run measure.py first)"
    runs = json.loads((ROOT / "out/borders_debug.json").read_text())["runs"]

    cells_html = "".join(
        f"<figure class='cell' tabindex='0' data-cap='{html.escape(cap)}'>"
        f"{svg}<figcaption>{html.escape(cap)}</figcaption></figure>"
        for r, svg in render_cells(runs)
        for cap in [f"{r['tag']} — {r['kind']} {r['name']} · "
                    f"mean {r['mean_dev']}px · max {r['max_dev']}px"])

    vb, _ = svg_inner(ROOT / "out/layers" / f"{LAYERS[0]}.svg")
    groups, toggles = [], []
    for name in LAYERS:
        _, inner = svg_inner(ROOT / "out/layers" / f"{name}.svg")
        op = f' opacity="{OPACITY[name]}"' if name in OPACITY else ""
        groups.append(f'<g id="lyr_{name}"{op}>{inner}</g>')
        toggles.append(f"<label><input type='checkbox' checked "
                       f"data-layer='lyr_{name}'> {LAYER_LABEL[name]}</label>")
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
  .tile .num {{ font-size: 20px; font-weight: 600;
                font-variant-numeric: tabular-nums; }}
  .tile .cap {{ font-size: 12px; color: var(--muted); }}
  .toggles {{ display: flex; gap: 18px; margin: 0 0 8px; font-size: 13px;
              color: var(--muted); flex-wrap: wrap; }}
  .toggles input {{ accent-color: #8a5fbf; }}
  #viewport {{ border: 1px solid var(--line); border-radius: 8px;
               height: 640px; overflow: hidden; cursor: grab;
               background: #fff; touch-action: none; position: relative; }}
  #viewport svg {{ display: block; transform-origin: 0 0; }}
  #lyr_L1_basemap path[data-name] {{ pointer-events: stroke; }}
  #tip {{ position: fixed; display: none; pointer-events: none;
          background: rgba(20,20,20,0.85); color: #fff; font-size: 12px;
          padding: 3px 8px; border-radius: 4px; z-index: 30;
          white-space: nowrap; }}
  .hint {{ font-size: 12px; color: var(--muted); margin: 6px 0 0; }}
  pre {{ background: var(--panel); border: 1px solid var(--line);
         border-radius: 8px; padding: 12px; overflow-x: auto;
         font-size: 12px; line-height: 1.45; }}
  .scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; font-size: 13px; }}
  th, td {{ border: 1px solid var(--line); padding: 5px 9px;
            text-align: left; vertical-align: top; }}
  th {{ background: var(--panel); }}
  .grid {{ display: grid; grid-template-columns:
           repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }}
  .cell {{ margin: 0; border: 1px solid var(--line); border-radius: 8px;
           overflow: hidden; cursor: zoom-in; background: #fff; }}
  .cell:hover, .cell:focus {{ border-color: #8a5fbf; outline: none; }}
  .cell svg {{ display: block; width: 100%; height: auto; }}
  .cell figcaption {{ font-size: 11px; color: var(--muted);
                      padding: 6px 8px; border-top: 1px solid var(--line);
                      background: var(--panel); }}
  #lightbox {{ position: fixed; inset: 0; display: none; z-index: 20;
               background: rgba(0,0,0,0.72); cursor: zoom-out;
               align-items: center; justify-content: center;
               flex-direction: column; gap: 10px; padding: 4vh 4vw; }}
  #lightbox.open {{ display: flex; }}
  #lightbox .box {{ background: #fff; border-radius: 10px;
                    width: min(88vh, 92vw); }}
  #lightbox .box svg {{ display: block; width: 100%; height: auto; }}
  #lightbox .cap {{ color: #eee; font-size: 13px; text-align: center; }}
</style>

<h1>Borders — annotation alignment review</h1>
<p class="hint">Basemap at 35% under boundary lines (L7) and their
annotations (L8). Every colored stroke should ride its border; every
border on a real feature should carry its label.</p>
<div class="tiles">{stat_tiles(measure)}</div>

<h2>Map</h2>
<div class="toggles">{"".join(toggles)}</div>
<div id="viewport">{map_svg}</div>
<p class="hint">drag to pan · wheel/pinch to zoom · double-click to
reset · hover a basemap street for its name</p>

<h2>Worst-aligned runs (closeups)</h2>
<p class="hint">Dark = administrative border; colored dash = annotation
stroke. Worst first — click any cell to enlarge.</p>
<div class="grid">{cells_html}</div>

<h2>Metrics</h2>
<pre>{html.escape(measure)}</pre>

<h2>Goal</h2>
{md_to_html(md_section(readme, "Metrics & bars"))}

<h2>Results log</h2>
{md_to_html(md_section(readme, "Results log"))}

<div id="lightbox"><div class="box"></div><div class="cap"></div></div>
<div id="tip"></div>

<script>
  const vp = document.getElementById('viewport');
  const svg = document.getElementById('map');
  let sc = 0.34, tx = 0, ty = 0, drag = null, moved = false;
  const apply = () => svg.style.transform =
      `translate(${{tx}}px,${{ty}}px) scale(${{sc}})`;
  const fit = () => {{
    sc = vp.clientWidth / svg.viewBox.baseVal.width;
    svg.style.width = svg.viewBox.baseVal.width + 'px';
    svg.style.height = svg.viewBox.baseVal.height + 'px';
    tx = 0; ty = 0; apply();
  }};
  vp.addEventListener('pointerdown', e => {{
    drag = {{x: e.clientX - tx, y: e.clientY - ty}}; moved = false;
    vp.setPointerCapture(e.pointerId); vp.style.cursor = 'grabbing';
  }});
  vp.addEventListener('pointermove', e => {{
    if (drag) {{ tx = e.clientX - drag.x; ty = e.clientY - drag.y;
                 moved = true; apply(); }}
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

  // layer toggles
  document.querySelectorAll('.toggles input').forEach(cb =>
    cb.addEventListener('change', () => {{
      document.getElementById(cb.dataset.layer).style.display =
          cb.checked ? '' : 'none';
    }}));

  // street-name tooltip (basemap paths carry data-name)
  const tip = document.getElementById('tip');
  vp.addEventListener('pointerover', e => {{
    const t = e.target.closest('[data-name]');
    if (t) {{ tip.textContent = t.dataset.name; tip.style.display = 'block'; }}
  }});
  vp.addEventListener('pointerout', e => {{
    if (e.target.closest('[data-name]')) tip.style.display = 'none';
  }});
  vp.addEventListener('pointermove', e => {{
    if (tip.style.display === 'block') {{
      tip.style.left = (e.clientX + 14) + 'px';
      tip.style.top = (e.clientY + 14) + 'px';
    }}
  }}, {{passive: true}});

  // closeup lightbox
  const lb = document.getElementById('lightbox');
  const open = cell => {{
    lb.querySelector('.box').innerHTML = cell.querySelector('svg').outerHTML;
    lb.querySelector('.cap').textContent = cell.dataset.cap;
    lb.classList.add('open');
  }};
  document.querySelectorAll('.cell').forEach(c => {{
    c.addEventListener('click', () => open(c));
    c.addEventListener('keydown', e => {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); open(c); }}
    }});
  }});
  lb.addEventListener('click', () => lb.classList.remove('open'));
  document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') lb.classList.remove('open');
  }});
</script>
"""
    (HERE / "review.html").write_text(page)
    print(f"wrote {HERE / 'review.html'} ({len(page) / 1024:.0f}K)")


if __name__ == "__main__":
    main()
