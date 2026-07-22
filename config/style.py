"""Typographic style config — THE place to iterate on the look.

Everything visual lives here: palette, fonts, per-layer type hierarchy.
Font stacks fall back gracefully in a browser; swap in licensed print
fonts before publishing (see README licensing note).
"""

BODY_FONT = "Avenir Next, Helvetica Neue, Arial, sans-serif"
HERO_FONT = "Arial Rounded MT Bold, Cooper Black, Chalkboard SE, sans-serif"

PAPER = "#faf7f0"

# One playful color per neighborhood hero label (rainbow-map style).
# Keys are matched against feature names; UNASSIGNED cycles for the rest.
HERO_COLORS = {
    "Union Square": "#d13c8f",
    "Davis Square": "#e8542a",
    "Winter Hill": "#7a3fbf",
}
HERO_CYCLE = ["#d13c8f", "#e8542a", "#2f8f4e", "#2f6aa8", "#e8a02a", "#7a3fbf"]

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
