"""Hero layout search — algorithm 4 in README.md.

Undistorted glyph outlines; the layout is *searched* over discrete
choices instead of bending letters:

  - text candidates: the full name + config HERO_VARIANTS, with the
    SQUARE→SQ rule (HERO_ABBREVIATIONS) applied to every form, and every
    allowed line break (spaces; "-" marks optional hyphenated breaks);
  - axis: the polygon's long axis (phase 2). Phase 3 adds an angle sweep,
    region splits and outline-level containment; phase 6 curved baselines.

Each candidate is sized line by line: a line sits in a band as tall as
its cap height, and gets the widest interval along the axis where the
whole band is inside the (inward-buffered) polygon. Score = inked box
legibility first — the smallest line's size × (1 − penalty) — with
total ink as a tiebreak, so shortenings and hyphen breaks must win by a
margin, and one giant short line can't buy the win (run 1 lesson).
"""

import itertools
import math
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from config.words import HERO_ABBREVIATIONS, HERO_VARIANTS  # noqa: E402

# score penalties (fractions of ink): the full name should win ties
PENALTY = {"abbrev": 0.08, "hyphen": 0.12, "variant": 0.04}
MAX_LINES = 3
LEADING = 0.30   # gap between stacked lines, as a fraction of cap height
MARGIN = 3.0     # px kept clear of the polygon edge
MAX_SIZE = 220   # em size cap (px)
MAX_RATIO = 2.0  # biggest line ≤ 2× the smallest — one label, not a headline
                 # + footnote (run 1: SQ dwarfed ASSEMBLY, MA- dwarfed GOUN)


# --- text candidates -------------------------------------------------------

def forms(name: str):
    """(text, penalty) for the full name, its variants, and SQ forms."""
    out = {}
    for i, v in enumerate([name.upper()] + HERO_VARIANTS.get(name, [])):
        base = PENALTY["variant"] if i else 0.0
        words = v.split()
        for mask in itertools.product(*[(False, True) if w in HERO_ABBREVIATIONS
                                        else (False,) for w in words]):
            text = " ".join(HERO_ABBREVIATIONS[w] if m else w
                            for w, m in zip(words, mask))
            pen = base + PENALTY["abbrev"] * sum(mask)
            if text not in out or pen < out[text]:
                out[text] = pen
    return list(out.items())


def breakings(text: str):
    """Every way to set `text` in 1..MAX_LINES lines.

    Spaces break or stay spaces; each "-" is an optional hyphenated break
    (break → "BRICK-" / "BOTTOM", no break → "BRICKBOTTOM").
    Yields (lines, n_hyphen_breaks).
    """
    # tokens alternate: piece, joint, piece, joint, ...
    pieces, joints = [], []
    for wi, word in enumerate(text.split()):
        if wi:
            joints.append(" ")
        parts = word.split("-")
        for pi, part in enumerate(parts):
            if pi:
                joints.append("-")
            pieces.append(part)
    for brk in itertools.product((False, True), repeat=len(joints)):
        if sum(brk) + 1 > MAX_LINES:
            continue
        lines, cur, hyph = [], pieces[0], 0
        for joint, b, piece in zip(joints, brk, pieces[1:]):
            if b:
                if joint == "-":
                    cur += "-"
                    hyph += 1
                lines.append(cur)
                cur = piece
            else:
                cur += " " + piece if joint == " " else piece
        lines.append(cur)
        yield lines, hyph


def candidates(name: str):
    """[(lines, penalty)] — every form × every breaking, deduplicated."""
    seen = {}
    for text, pen in forms(name):
        for lines, hyph in breakings(text):
            key = tuple(lines)
            p = pen + PENALTY["hyphen"] * hyph
            if key not in seen or p < seen[key]:
                seen[key] = p
    return list(seen.items())


# --- font metrics ------------------------------------------------------------

class Metrics:
    def __init__(self, glyphs):
        self.gs, self.cmap, self.upm = glyphs["gs"], glyphs["cmap"], glyphs["upm"]
        b = glyphs["bounds"](self.cmap[ord("H")])
        self.cap = b[3] / self.upm  # cap height, em

    def advance(self, text: str) -> float:
        """Advance width of `text` in em (no kerning — phase 4)."""
        return sum(self.gs[self.cmap[ord(ch)]].width
                   for ch in text if ord(ch) in self.cmap) / self.upm


# --- geometry ----------------------------------------------------------------

def principal_axis(polygon):
    """(u, p): long axis of the min rotated rect, reading left→right,
    p pointing screen-down."""
    mrr = polygon.minimum_rotated_rectangle
    cs = list(mrr.exterior.coords)[:4]
    edges = [(cs[i], cs[(i + 1) % 4]) for i in range(4)]
    (ax, ay), (bx, by) = max(edges, key=lambda e: math.dist(*e))
    L = math.dist((ax, ay), (bx, by))
    ux, uy = (bx - ax) / L, (by - ay) / L
    if ux < 0:
        ux, uy = -ux, -uy
    px, py = -uy, ux
    if py < 0:
        px, py = -px, -py
    return (ux, uy), (px, py)


class Frame:
    """Axis-aligned view of a polygon: t along u, v along p."""

    def __init__(self, polygon, u, p):
        self.poly, self.u, self.p = polygon, u, p
        self.c = polygon.representative_point()
        self.reach = math.hypot(*(b - a for a, b in
                                  zip(polygon.bounds[:2], polygon.bounds[2:])))
        vs = [self.tv(xy)[1] for xy in polygon.exterior.coords]
        self.vmin, self.vmax = min(vs), max(vs)

    def tv(self, xy):
        dx, dy = xy[0] - self.c.x, xy[1] - self.c.y
        return dx * self.u[0] + dy * self.u[1], dx * self.p[0] + dy * self.p[1]

    def xy(self, t, v):
        return (self.c.x + self.u[0] * t + self.p[0] * v,
                self.c.y + self.u[1] * t + self.p[1] * v)

    def intervals(self, v):
        """t-intervals where the horizontal-in-frame line at v is inside."""
        R = self.reach
        cut = LineString([self.xy(-R, v), self.xy(R, v)]).intersection(self.poly)
        out = []
        for g in getattr(cut, "geoms", [cut]):
            if isinstance(g, LineString) and not g.is_empty:
                a, b = self.tv(g.coords[0])[0], self.tv(g.coords[-1])[0]
                out.append((min(a, b), max(a, b)))
        return out

    def band(self, v0, v1, samples=5):
        """t-intervals where the whole band v0..v1 is inside (sampled)."""
        acc = None
        for k in range(samples):
            iv = self.intervals(v0 + (v1 - v0) * k / (samples - 1))
            acc = iv if acc is None else [
                (max(a, c), min(b, d)) for a, b in acc for c, d in iv
                if min(b, d) > max(a, c)]
            if not acc:
                return []
        return acc

    def box(self, t0, t1, v0, v1):
        return Polygon([self.xy(t0, v0), self.xy(t1, v0),
                        self.xy(t1, v1), self.xy(t0, v1)])


# --- layout ------------------------------------------------------------------

def fit_lines(frame, lines, M):
    """Size and place `lines` as a centered stack. Returns rows or None.

    Fixed point: each line's size depends on its band's free width, and
    the band's position depends on every line's size.
    """
    fit_poly = frame.poly
    adv = [M.advance(ln) for ln in lines]
    height = frame.vmax - frame.vmin
    n = len(lines)
    sizes = [min(MAX_SIZE, height / (n * M.cap * (1 + LEADING)))] * n
    rows = None
    for _ in range(8):
        hs = [s * M.cap for s in sizes]
        total = sum(hs) + LEADING * sum((a + b) / 2 for a, b in zip(hs, hs[1:]))
        # center the stack on the frame's vertical middle of the free space
        v = (frame.vmin + frame.vmax) / 2 - total / 2
        rows, new = [], []
        for i, (ln, h) in enumerate(zip(lines, hs)):
            ivs = frame.band(v, v + h)
            best = max(ivs, key=lambda iv: iv[1] - iv[0], default=None)
            w = (best[1] - best[0]) if best else 0.0
            new.append(max(0.0, min(MAX_SIZE, w / adv[i])) if adv[i] else 0.0)
            rows.append({"line": ln, "v0": v, "v1": v + h, "iv": best})
            v += h + (LEADING * (h + hs[i + 1]) / 2 if i + 1 < n else 0)
        if all(abs(a - b) < 0.5 for a, b in zip(sizes, new)):
            break
        # damped: shrinking one line can free height for the others
        sizes = [0.5 * a + 0.5 * b for a, b in zip(sizes, new)]
    for r, s, a in zip(rows, sizes, adv):
        if r["iv"] is None or s <= 0:
            return None
        r["size"] = s
        w = s * a
        a0, a1 = r["iv"]
        mid = min(max((a0 + a1) / 2, a0 + w / 2), a1 - w / 2)
        r["t0"], r["t1"] = mid - w / 2, mid + w / 2
    # one label: clamp lines far bigger than the smallest, about their centers
    floor = min(r["size"] for r in rows)
    for r in rows:
        if r["size"] > MAX_RATIO * floor:
            _scale_row(r, MAX_RATIO * floor / r["size"])
    # exact check: every row's box inside; shrink offenders
    for _ in range(30):
        bad = [r for r in rows
               if not frame.box(r["t0"], r["t1"], r["v0"], r["v1"]).within(fit_poly)]
        if not bad:
            return rows
        for r in bad:
            _scale_row(r, 0.95)
    return None


def _scale_row(r, f):
    """Shrink a row's size and box by `f` about the box center."""
    mid, vm = (r["t0"] + r["t1"]) / 2, (r["v0"] + r["v1"]) / 2
    hw, hh = (r["t1"] - r["t0"]) / 2 * f, (r["v1"] - r["v0"]) / 2 * f
    r["size"] *= f
    r["t0"], r["t1"], r["v0"], r["v1"] = mid - hw, mid + hw, vm - hh, vm + hh


def search(polygon, name, M):
    """Best layout for `name` in `polygon`: (rows, frame, lines, penalty)."""
    inner = polygon.buffer(-MARGIN)
    if inner.is_empty:
        return None
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    u, p = principal_axis(inner)
    frame = Frame(inner, u, p)
    best = None
    for lines, pen in candidates(name):
        rows = fit_lines(frame, lines, M)
        if not rows:
            continue
        ink = sum((r["t1"] - r["t0"]) * (r["v1"] - r["v0"]) for r in rows)
        # legibility first (smallest line), ink as a ~1% tiebreak
        floor = min(r["size"] for r in rows)
        score = floor * (1 - pen) * (1 + 0.01 * ink / frame.poly.area)
        if best is None or score > best[0]:
            best = (score, rows, lines, pen)
    if best is None:
        return None
    return {"rows": best[1], "frame": frame, "lines": best[2], "penalty": best[3]}


def render(doc, result, M, fill):
    """Emit glyph outlines, undistorted, along each row's baseline."""
    from fontTools.pens.svgPathPen import SVGPathPen

    fr = result["frame"]
    (ux, uy), (px, py) = fr.u, fr.p
    for r in result["rows"]:
        k = r["size"] / M.upm
        pen_t = r["t0"]
        for ch in r["line"]:
            g = M.cmap.get(ord(ch))
            if g is None:
                continue
            bx, by = fr.xy(pen_t, r["v1"])  # baseline = bottom of cap band
            if ch != " ":
                sp = SVGPathPen(M.gs, ntos=lambda v: f"{v:.1f}")
                M.gs[g].draw(sp)
                # font units (x right, y up) → page: x along u, y along −p
                doc.raw(f'<path transform="matrix({ux * k:.5f} {uy * k:.5f} '
                        f'{-px * k:.5f} {-py * k:.5f} {bx:.2f} {by:.2f})" '
                        f'd="{sp.getCommands()}" fill="{fill}"/>')
            pen_t += M.gs[g].width * k
