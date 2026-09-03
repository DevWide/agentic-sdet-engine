#!/usr/bin/env bash
#
# Render the project's evidence images (README SVGs -> PNG, plus a Jaeger trace
# screenshot) without taking a single manual screenshot.
#
#   ./scripts/capture-evidence.sh              render PNGs from the existing SVGs (free)
#   ./scripts/capture-evidence.sh --regenerate re-run the CLI first (costs API credits)
#
# PNGs land in docs/images/png/, which is gitignored: they are derived artifacts,
# regenerable at any time, and the README itself uses the committed SVGs.

set -euo pipefail

cd "$(dirname "$0")/.."

SVG_DIR="docs/images"
PNG_DIR="docs/images/png"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
REGENERATE=false

for arg in "$@"; do
  case "$arg" in
    --regenerate) REGENERATE=true ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  for candidate in \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "$(command -v google-chrome || true)" \
    "$(command -v chromium || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CHROME="$candidate"; break; fi
  done
fi
if [ ! -x "$CHROME" ]; then
  echo "error: no Chromium-based browser found; PNG rendering needs one." >&2
  exit 1
fi

mkdir -p "$PNG_DIR"

if [ "$REGENERATE" = true ]; then
  echo "==> Regenerating SVGs (this calls the OpenAI API)"
  agentic-sdet run tests/fixtures/flaky_feature.txt --save-svg "$SVG_DIR/demo.svg" || true
  agentic-sdet eval --save-svg "$SVG_DIR/eval.svg"
fi

# Rich writes the canvas size into the SVG viewBox; reuse it so nothing is cropped.
svg_to_png() {
  local svg="$1" out="$2"
  [ -f "$svg" ] || { echo "    skip: $svg not found"; return; }
  local dims
  dims=$(python3 -c "
import re, sys
m = re.search(r'viewBox=\"([^\"]+)\"', open('$svg').read())
if not m:
    sys.exit('no viewBox')
_, _, w, h = m.group(1).split()
print(int(float(w)), int(float(h)))
")
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 \
    --window-size="${dims% *},${dims#* }" \
    --screenshot="$out" "file://$PWD/$svg" >/dev/null 2>&1
  echo "    $out"
}

echo "==> Rendering SVGs to PNG"
svg_to_png "$SVG_DIR/demo.svg" "$PNG_DIR/demo.png"
svg_to_png "$SVG_DIR/eval.svg" "$PNG_DIR/eval.png"

echo "==> Capturing the most recent Jaeger trace"
if ! curl -sf -o /dev/null --max-time 3 "$JAEGER_URL"; then
  echo "    skip: Jaeger not reachable at $JAEGER_URL (run: docker compose up -d)"
else
  TRACE_ID=$(curl -s --max-time 5 \
    "$JAEGER_URL/api/traces?service=agentic-sdet-engine&limit=20" | python3 -c "
import json, sys
data = json.load(sys.stdin).get('data', [])
runs = []
for t in data:
    roots = [s for s in t['spans']
             if not any(r['refType'] == 'CHILD_OF' for r in s.get('references', []))]
    if roots and roots[0]['operationName'] == 'sdet.run':
        runs.append((len(t['spans']), t['traceID']))
print(max(runs)[1] if runs else '')
")
  if [ -z "$TRACE_ID" ]; then
    echo "    skip: no sdet.run trace found — run the CLI once with Jaeger up"
  else
    # 1500px wide so the operation column is not truncated; 450 tall fits five spans.
    "$CHROME" --headless --disable-gpu --hide-scrollbars \
      --force-device-scale-factor=2 --window-size=1500,450 \
      --virtual-time-budget=12000 \
      --screenshot="$PNG_DIR/jaeger.png" \
      "$JAEGER_URL/trace/$TRACE_ID" >/dev/null 2>&1
    echo "    $PNG_DIR/jaeger.png  (trace ${TRACE_ID:0:8})"

    if command -v sips >/dev/null 2>&1; then
      sips -Z 1280 "$PNG_DIR/jaeger.png" --out "$PNG_DIR/social_preview.png" >/dev/null 2>&1
      sips --padToHeightWidth 640 1280 --padColor FFFFFF \
        "$PNG_DIR/social_preview.png" >/dev/null 2>&1
      echo "    $PNG_DIR/social_preview.png  (1280x640, for GitHub Settings > Social preview)"
    fi
  fi
fi

echo
echo "Done. Images in $PNG_DIR/"
