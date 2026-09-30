"""Typographic style config — THE place to iterate on the look.

Everything visual lives here: palette, fonts, per-layer type hierarchy.
Font stacks fall back gracefully in a browser; swap in licensed print
fonts before publishing (see README licensing note).
"""

# One family for every label (user, 2026-09-30): Barlow Condensed, OFL,
# vendored in fonts/ and embedded (subset) into each SVG so the map looks
# the same everywhere. Heroes use glyph outlines from HERO_FONT_FILE.
BODY_FONT = "Barlow Condensed, Avenir Next Condensed, Arial Narrow, sans-serif"
HERO_FONT = BODY_FONT
EMBED_FONTS = {  # font-weight → file
    500: "fonts/BarlowCondensed-Medium.ttf",
    600: "fonts/BarlowCondensed-SemiBold.ttf",
    700: "fonts/BarlowCondensed-Bold.ttf",
    800: "fonts/BarlowCondensed-ExtraBold.ttf",
    900: "fonts/BarlowCondensed-Black.ttf",
}

PAPER = "#faf7f0"

# Hero label colors (user, 2026-09-30): an area named for a T stop takes
# its line's color — Davis/Porter red, Ball/Magoun/Union/East Somerville
# green (GLX), Assembly orange. Same-line neighbors (Davis|Porter,
# Ball|Magoun, Union|East Somerville) alternate two shades of the line.
# Every other area gets a neutral that is never a line color, graph-colored
# so neighbors differ. HERO_COLORS pins individual areas.
HERO_TRANSIT = {
    "Davis Square": "red", "Porter Square": "red",
    "Ball Square": "green", "Magoun Square": "green",
    "Union Square": "green", "East Somerville": "green",
    "Assembly Square": "orange",
}
LINE_SHADES = {
    "red": ["#da291c", "#9c1d14"],
    "green": ["#00843d", "#005c2b"],
    "orange": ["#ed8b00", "#b06400"],
}
HERO_NEUTRALS = ["#2f6aa8", "#7a3fbf", "#d13c8f", "#4f5d75", "#1f6f8b",
                 "#8e4585", "#6b5b4e"]
HERO_COLORS = {"Winter Hill": "#7a3fbf"}
# the SOMERVILLE title's letter colors
HERO_CYCLE = ["#d13c8f", "#e8542a", "#2f8f4e", "#2f6aa8", "#e8a02a", "#7a3fbf"]
# hero typeface: glyph outlines come from this file (fonttools), so the
# print doesn't depend on installed fonts
HERO_FONT_FILE = "fonts/BarlowCondensed-ExtraBold.ttf"

LAYERS = {
    # Areas — small repeated text conforming to the polygon
    "neighborhood_fill": {
        "font_size": 9,
        "font_family": BODY_FONT,
        "fill": "#c3b9a6",
        "letter_spacing": 0.5,
    },
    "park_fill": {
        "font_size": 11,
        "font_family": BODY_FONT,
        "font_weight": "600",
        "fill": "#4f9d5d",
        "letter_spacing": 0.5,
    },
    "water_fill": {
        "font_size": 13,
        "font_family": BODY_FONT,
        "font_weight": "500",
        "fill": "#3f7fbf",
        "letter_spacing": 1.5,
    },
    # Streets — name repeated along the centerline, sized by class
    "street_major": {
        "font_size": 18,
        "font_family": BODY_FONT,
        "font_weight": "700",
        "fill": "#3a3a3a",
        "letter_spacing": 1,
        # paper-colored halo keeps streets legible over area fills
        "stroke": PAPER,
        "stroke_width": 4,
        "paint_order": "stroke",
    },
    "street_mid": {
        "font_size": 14,
        "font_family": BODY_FONT,
        "font_weight": "600",
        "fill": "#4a4a4a",
        "letter_spacing": 0.5,
        "stroke": PAPER,
        "stroke_width": 3.5,
        "paint_order": "stroke",
    },
    "street_minor": {
        "font_size": 12,
        "font_family": BODY_FONT,
        "font_weight": "500",
        "fill": "#6b6b6b",
        "letter_spacing": 0.5,
        "stroke": PAPER,
        "stroke_width": 3,
        "paint_order": "stroke",
    },
    # The Somerville Community Path
    "path": {
        "font_size": 13,
        "font_family": BODY_FONT,
        "font_weight": "600",
        "fill": "#2f8f4e",
        "letter_spacing": 1,
        "stroke": PAPER,
        "stroke_width": 3,
        "paint_order": "stroke",
    },
    # T station labels (fill color comes from the line, see config/words.py)
    "station": {
        "font_size": 16,
        "font_family": BODY_FONT,
        "font_weight": "800",
        "letter_spacing": 0.5,
        "text_anchor": "middle",
        "stroke": PAPER,
        "stroke_width": 4,
        "paint_order": "stroke",
    },
    # Labels naming what a neighborhood border runs along
    "border_label": {
        "font_size": 13,
        "font_family": BODY_FONT,
        "font_weight": "700",
        "letter_spacing": 1,
        "text_anchor": "middle",
        "stroke": PAPER,
        "stroke_width": 3.5,
        "paint_order": "stroke",
    },
    # Perceived borders (the line locals draw): a soft band under the
    # street, its name repeated along it
    "perceived": {
        "band": "#e8a02a",
        "band_width": 16,
        "band_opacity": 0.35,
        "font_size": 12,
        "font_family": BODY_FONT,
        "font_weight": "700",
        "fill": "#9a6412",
        "letter_spacing": 1.5,
        "stroke": PAPER,
        "stroke_width": 3,
        "paint_order": "stroke",
    },
    # Neighborhood hero labels — big, arched, layered over everything
    "hero": {
        "font_size": 58,
        "font_family": HERO_FONT,
        "font_weight": "900",
        "letter_spacing": 2,
        "stroke": PAPER,
        "stroke_width": 3,
        "paint_order": "stroke",
    },
}
