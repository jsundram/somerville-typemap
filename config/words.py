"""Typographic content config — which words fill which spaces.

This is deliberately separate from the geometry pipeline so the map's
voice can be iterated without touching code.
"""

# Override the words used to fill an area, keyed by feature name.
# Default is the feature's own name (lowercased for parks, uppercased
# for water). Add whimsy here, e.g.:
#   "Duck Village": ["duck village", "quack"],
WORD_OVERRIDES: dict[str, list[str]] = {
    "Mystic River": ["MYSTIC RIVER", "~"],
}

# T stations: which line serves each (drives label color).
STATION_LINES = {
    "Davis": "red",
    "Porter": "red",
    "Assembly": "orange",
    "Sullivan Square": "orange",
    "Wellington": "orange",
    "Community College": "orange",
    "Union Square": "green",
    "East Somerville": "green",
    "Gilman Square": "green",
    "Magoun Square": "green",
    "Ball Square": "green",
    "Medford/Tufts": "green",
}
LINE_COLORS = {"red": "#da291c", "orange": "#ed8b00", "green": "#00843d"}

# Stations rendered even though the point sits just outside the city clip.
STATION_KEEP = set(STATION_LINES)
