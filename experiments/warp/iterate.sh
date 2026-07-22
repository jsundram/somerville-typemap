#!/bin/sh
# One measured iteration of the warp loop:
#   render_sheet.py <algo> -> sheet.svg  ->  headless Chrome -> sheet.png
#   -> measure.py -> coverage/spill table on stdout.
#
#   ./iterate.sh [algorithm]     # default: baseline
#
# Chrome (not rsvg-convert) because the final map is browser-viewed, so
# Chrome's font matching is the target surface.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
ALGO="${1:-baseline}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

uv run "$HERE/render_sheet.py" "$ALGO"

# sheet dimensions from the layout json (cols x cell, rows x cell)
read -r W H <<EOF
$(python3 -c "
import json, math
m = json.load(open('$HERE/sheet_layout.json'))
rows = math.ceil(len(m['cells']) / m['cols'])
print(m['cols'] * m['cell'], rows * m['cell'])
")
EOF

"$CHROME" --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=1 \
  --default-background-color=FFFFFFFF \
  --window-size="$W,$H" \
  --screenshot="$HERE/sheet.png" \
  "file://$HERE/sheet.svg" 2>/dev/null
echo "wrote $HERE/sheet.png (${W}x${H})"

uv run "$HERE/measure.py" "$HERE/sheet.png" | tee "$HERE/measure.txt"
