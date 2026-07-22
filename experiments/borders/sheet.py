# /// script
# requires-python = ">=3.11"
# ///
"""Closeup contact sheet of the worst-aligned border annotations.

Each cell: the border run (dark), its annotation stroke (colored), and
the deviation numbers — so a bad match is diagnosable at a glance.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
HERE = Path(__file__).parent
CELL, PAD, COLS, N = 420, 30, 4, 16
COLORS = {"street": "#3a3a3a", "rail": "#8a5fbf", "path": "#2f8f4e",
          "water": "#3f7fbf", "waterbody": "#3f7fbf"}
BARS = {"street": 8, "path": 8, "water": 8, "waterbody": 8, "rail": 25}


def main():
    runs = json.loads((ROOT / "out/borders_debug.json").read_text())["runs"]
    worst = sorted((r for r in runs if r["kind"]),
                   key=lambda r: r["mean_dev"] / BARS.get(r["kind"], 8),
                   reverse=True)[:N]
    rows = (len(worst) + COLS - 1) // COLS
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{COLS * CELL}" '
           f'height="{rows * CELL}" viewBox="0 0 {COLS * CELL} {rows * CELL}">',
           '<rect width="100%" height="100%" fill="#ffffff"/>']

    for i, r in enumerate(worst):
        cx, cy = (i % COLS) * CELL, (i // COLS) * CELL
        pts = r["run"] + [p for part in r["stroke"] for p in part]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(xs) - min(xs) or 1, max(ys) - min(ys) or 1
        s = min((CELL - 2 * PAD) / w, (CELL - 2 * PAD) / h)
        ox = cx + PAD - min(xs) * s + (CELL - 2 * PAD - w * s) / 2
        oy = cy + PAD - min(ys) * s + (CELL - 2 * PAD - h * s) / 2

        def d_of(coords):
            return "M " + " L ".join(f"{x * s + ox:.1f},{y * s + oy:.1f}"
                                     for x, y in coords)

        out.append(f'<rect x="{cx}" y="{cy}" width="{CELL}" height="{CELL}" '
                   f'fill="none" stroke="#eeeeee"/>')
        out.append(f'<path d="{d_of(r["run"])}" fill="none" stroke="#222222" '
                   f'stroke-width="2"/>')
        for part in r["stroke"]:
            out.append(f'<path d="{d_of(part)}" fill="none" '
                       f'stroke="{COLORS[r["kind"]]}" stroke-width="2.5" '
                       f'stroke-dasharray="6 4" opacity="0.85"/>')
        out.append(f'<text x="{cx + 8}" y="{cy + 16}" font-size="11" '
                   f'font-family="monospace" fill="#666666">{r["tag"][:44]}</text>')
        out.append(f'<text x="{cx + 8}" y="{cy + 30}" font-size="11" '
                   f'font-family="monospace" fill="#666666">{r["kind"]} '
                   f'{r["name"][:28]} mean {r["mean_dev"]} max {r["max_dev"]}</text>')
    out.append("</svg>")
    (HERE / "sheet.svg").write_text("\n".join(out))
    print(f"wrote {HERE / 'sheet.svg'} ({len(worst)} cells)")


if __name__ == "__main__":
    main()
