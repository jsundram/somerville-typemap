"""Minimal SVG document builder for typographic maps.

Everything visible is a <text> element; geometry only ever appears as
invisible <path>s in <defs> (for textPath baselines and clipPaths).
"""

from xml.sax.saxutils import escape, quoteattr

# Average glyph advance as a fraction of font size, for a typical sans.
# Only used to decide how many repetitions to emit; overflow past a path
# end or a clip edge is dropped/clipped, so precision is not critical.
CHAR_WIDTH = 0.44  # Barlow Condensed ≈ 0.36–0.40 em/char + letter-spacing slack


def est_width(text: str, font_size: float) -> float:
    """Estimated rendered width of `text` in user units."""
    return len(text) * CHAR_WIDTH * font_size


def repeat_to_length(text: str, length: float, font_size: float, sep: str = " · ") -> str:
    """Repeat `text` (with separators) until it spans at least `length`."""
    unit = text + sep
    n = max(1, int(length / max(est_width(unit, font_size), 1e-6)) + 2)
    return (unit * n).rstrip()


def path_d(coords, close: bool = False) -> str:
    """SVG path data for a polyline given (x, y) coords."""
    pts = list(coords)
    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    return d + " Z" if close else d


class SvgDoc:
    """Collects defs + body elements, then serializes."""

    def __init__(self, width: float, height: float, background: str | None = "#faf7f0",
                 id_prefix: str = ""):
        self.width, self.height = width, height
        self.background = background
        self.id_prefix = id_prefix  # keeps ids unique when docs are combined
        self._defs: list[str] = []
        self._body: list[str] = []
        self._n = 0

    def _next_id(self, prefix: str) -> str:
        self._n += 1
        return f"{self.id_prefix}{prefix}{self._n}"

    def add_path_def(self, d: str) -> str:
        pid = self._next_id("p")
        self._defs.append(f'<path id="{pid}" d="{d}" fill="none"/>')
        return pid

    def add_clip(self, ds: list[str]) -> str:
        cid = self._next_id("clip")
        paths = "".join(f'<path d="{d}"/>' for d in ds)
        self._defs.append(f'<clipPath id="{cid}">{paths}</clipPath>')
        return cid

    def text_on_path(self, d: str, text: str, style: dict, start_offset: str | None = None, group: list | None = None):
        """Emit `text` flowing along path `d`. Style keys → presentation attrs."""
        pid = self.add_path_def(d)
        attrs = style_attrs(style)
        so = f' startOffset={quoteattr(start_offset)}' if start_offset else ""
        el = (f'<text {attrs}><textPath href="#{pid}"{so}>'
              f'{escape(text)}</textPath></text>')
        (group if group is not None else self._body).append(el)

    def text(self, x: float, y: float, content: str, style: dict, group: list | None = None):
        """A plain positioned label (e.g. station names)."""
        el = (f'<text x="{x:.2f}" y="{y:.2f}" {style_attrs(style)}>'
              f'{escape(content)}</text>')
        (group if group is not None else self._body).append(el)

    def group(self, elements: list, clip_id: str | None = None, opacity: float | None = None):
        attrs = ""
        if clip_id:
            attrs += f' clip-path="url(#{clip_id})"'
        if opacity is not None:
            attrs += f' opacity="{opacity}"'
        self._body.append(f"<g{attrs}>" + "".join(elements) + "</g>")

    def raw(self, element: str):
        self._body.append(element)

    def tostring(self) -> str:
        bg = (f'<rect width="100%" height="100%" fill="{self.background}"/>\n'
              if self.background else "")
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}">\n'
            + bg
            + f"<defs>{_font_style()}{''.join(self._defs)}</defs>\n"
            + "\n".join(self._body)
            + "\n</svg>\n"
        )

    def write(self, path):
        with open(path, "w") as f:
            f.write(self.tostring())


_FONT_CSS = ""


def embed_fonts(family: str, files: dict, root) -> None:
    """Embed subset font files (weight → path) as @font-face data URIs in
    every SVG written afterwards — SVGs shown via <img> can't fetch fonts,
    and the print must not depend on what's installed."""
    import base64
    import io

    from fontTools import subset
    from fontTools.ttLib import TTFont

    global _FONT_CSS
    text = ("".join(chr(c) for c in range(0x20, 0x7F))
            + "·»«–—’‘“”•…°éèáàüöñç")
    faces = []
    for weight, path in sorted(files.items()):
        font = TTFont(str(root / path))
        sub = subset.Subsetter(subset.Options())
        sub.populate(text=text)
        sub.subset(font)
        buf = io.BytesIO()
        font.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        faces.append(f"@font-face{{font-family:'{family}';font-weight:{weight};"
                     f"src:url(data:font/ttf;base64,{b64}) format('truetype')}}")
    _FONT_CSS = "".join(faces)


def _font_style() -> str:
    return f"<style>{_FONT_CSS}</style>" if _FONT_CSS else ""


def write_combined(path, docs: list[SvgDoc], width: float, height: float,
                   background: str = "#faf7f0"):
    """Merge several layer docs (distinct id_prefixes!) into one SVG."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{background}"/>',
        "<defs>" + _font_style() + "".join(d for doc in docs for d in doc._defs)
        + "</defs>",
    ]
    parts += [f'<g id="{doc.id_prefix or i}">' + "\n".join(doc._body) + "</g>"
              for i, doc in enumerate(docs)]
    parts.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(parts))


def style_attrs(style: dict) -> str:
    """{'font_size': 12, 'fill': '#333', ...} → SVG presentation attributes."""
    mapping = {
        "font_size": "font-size",
        "font_family": "font-family",
        "font_weight": "font-weight",
        "fill": "fill",
        "letter_spacing": "letter-spacing",
        "stroke": "stroke",
        "stroke_width": "stroke-width",
        "paint_order": "paint-order",
        "text_anchor": "text-anchor",
        "opacity": "opacity",
    }
    parts = []
    for key, attr in mapping.items():
        if key in style:
            parts.append(f"{attr}={quoteattr(str(style[key]))}")
    return " ".join(parts)
