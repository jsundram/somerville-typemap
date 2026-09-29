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
    "Lechmere": "green",
}
LINE_COLORS = {"red": "#da291c", "orange": "#ed8b00", "green": "#00843d"}

# Stations rendered even though the point sits just outside the city clip.
STATION_KEEP = set(STATION_LINES)

# OSM names rail corridors by route; locals name them by line.
RAIL_RENAME = {
    "New Hampshire Route": "Lowell Line",
    "New Hampshire Route Main Line": "Lowell Line",
    "Fitchburg Route": "Fitchburg Line",
    "Fitchburg Route Main Line": "Fitchburg Line",
    "Eastern Route": "Eastern Line",
    "B&A Eastbound": "Grand Junction",
    "B&A Westbound": "Grand Junction",
    "Green Line (D)": "Green Line",
    "Green Line (E)": "Green Line",
}

# When an unnamed track could inherit from several lines, prefer these.
# (No Green Line here: the GLX rides existing commuter corridors, and a
# border should read as one consistent line — the corridor's, not both.)
RAIL_MAINLINES = ["Fitchburg Line", "Lowell Line", "Eastern Line"]

# The greenway spine: the Community Path and its continuations past Davis
# toward Alewife and Arlington. Rendered across the whole frame (other
# named cycleways are ignored — this layer is about the path, not every
# bike lane).
PATH_FAMILY = [
    "Somerville Community Path",
    "Community Path",
    "Alewife Linear Park",
    "Minuteman/Linear Park Connector",
    "Minuteman Bikeway",
    "Alewife Brook Greenway",
]

# Adjacent municipalities (rainbow-map style color blocks around the city).
# Only towns listed here are rendered. display: what the label says —
# within our frame Boston's visible sliver is Charlestown.
TOWNS = {
    "Medford": {"color": "#c8412f"},
    "Cambridge": {"color": "#2f8f4e"},
    "Everett": {"color": "#7a3fbf"},
    "Boston": {"color": "#e8a02a", "display": "Charlestown"},
    "Arlington": {"color": "#2f6aa8"},
    "Malden": {"color": "#d13c8f"},
    "Chelsea": {"color": "#8a8378"},
}

# Perceived borders: the line locals draw, as opposed to the legal one.
# Each route follows the named streets in order (junction to junction);
# the first/last street run out toward start/end, or stop where they
# cross the waterway named in end_at. Not accurate —
# semantically useful (user, 2026-09-29: "my mental map … Cambridge St to
# Beacon St to Somerville Ave to Mass Ave as the edge with Cambridge").
PERCEIVED_BORDERS = [
    {
        "town": "Cambridge",
        "route": ["Cambridge Street", "Beacon Street", "Somerville Avenue",
                  "Massachusetts Avenue"],
        "start": "east",
        "end": "west",
        # Cambridge ends at the brook; Mass Ave beyond it is Arlington
        "end_at": "Alewife Brook",
    },
]

# How a street is named along a perceived border.
PERCEIVED_LABELS = {"Massachusetts Avenue": "Mass Ave"}
