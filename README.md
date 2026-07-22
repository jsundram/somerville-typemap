# somerville-typemap

A **typographic neighborhood map of Somerville, MA** — a print-oriented SVG
where essentially nothing is drawn with lines: every feature is rendered as
text.

- **Streets** — the street name repeated along its path (`<textPath>`),
  sized by road class.
- **Areas** (parks, water, land) — filled with small repeated text that
  conforms to the polygon shape, in the style of the
  [Axis Maps typographic maps](https://design-milk.com/typographic-maps-by-axis-maps/):
  - *contour fill* — text flows along nested inward-buffered rings
    (the rippled look, used for water);
  - *line-pack fill* — straight rows of repeated text clipped to the
    polygon (used for parks and neighborhood interiors).
- **Neighborhoods** — one big, playful, arched hero label each
  (Davis, Ball, Teele, Union, Winter Hill, Spring Hill, Prospect Hill,
  Magoun, East Somerville, Assembly, Ten Hills, …), layered over everything.

## Data sources & licensing

| Layer | Source | License / note |
|---|---|---|
| Streets, parks, water, Community Path, T stops | [OpenStreetMap](https://www.openstreetmap.org/) via the Overpass API | © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). Attribution required on any published map. |
| Neighborhood boundaries | [simplemaps Somerville neighborhoods](https://simplemaps.com/city/somerville/neighborhoods) | ⚠️ **simplemaps data has its own terms of use.** Fine for a personal build; review/replace before this becomes a sellable or printed product. Their boundaries are editorial/generalized — treat as a starting layer to be hand-nudged. |
| Typographic content, fonts, palette | hand-authored in [`config/`](config/) | Fonts must be licensed for print use — check before publishing. |

## Layout

```
typemap/            the engine: geometry, fills, SVG emission
config/             words, fonts, palette, type hierarchy — the iterate-here layer
data/fixtures/      tiny hand-made geometries for engine development
data/cache/         raw Overpass responses (network-tolerant cache)
out/                rendered SVGs (not committed)
render_fixture.py   renders the engine-proving fixture scene
```

## Running

Scripts use [PEP 723](https://peps.python.org/pep-0723/) inline dependencies —
run them with [`uv`](https://docs.astral.sh/uv/):

```sh
uv run render_fixture.py   # → out/fixture.svg
```

## Build order

1. ✅ Scaffold
2. Typographic-fill engine, proven against a hand-made fixture (no network)
3. Overpass fetch + simplemaps georeferencing
4. Full Somerville assembly & styling iteration
