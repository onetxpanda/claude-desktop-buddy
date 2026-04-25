#!/usr/bin/env bash
# Run from repo root: support/native/capture_screens.sh
# Sweeps the firmware through each major screen via scripted button input,
# saves PNG layouts to docs/emulator/screenshots/.
#
# Button script syntax (EMULATOR_INPUT env): "BTN:start-end" comma-separated.
# A = BtnA, B = BtnB, P = BtnPWR. Time in ms since process start. Multiple
# entries are layered (e.g. simulate "long press A then tap B").
#
# A-tap   = quick press        (A:500-550)
# A-long  = press for >=600ms  (A:500-1300)   → LongPress event
# B-tap   = quick press        (B:1500-1550)
set -euo pipefail

OUT_DIR="${OUT_DIR:-docs/emulator/screenshots}"
mkdir -p "$OUT_DIR"

shoot() {
  local name=$1 board=$2 input=$3 at_ms=$4 exit_ms=$5
  local out="$OUT_DIR/${board}_${name}.png"
  local tmp; tmp=$(mktemp -t emu_${board}_${name}_XXXXXX.ppm)
  EMULATOR_INPUT="$input" \
  SCREENSHOT_FILE="$tmp" \
  SCREENSHOT_AT_MS="$at_ms" \
  EXIT_AFTER_MS="$exit_ms" \
    timeout 15 xvfb-run -a -s "-screen 0 800x600x24" \
      ".pio/build/emulator_${board}/program" >/dev/null 2>&1 || true
  if [[ -s "$tmp" ]]; then
    convert "$tmp" "$out"
    rm -f "$tmp"
    echo "  ✓ $out"
  else
    echo "  ✗ $name ($board) — no PPM produced"
  fi
}

for board in stickc core2; do
  echo "== $board =="
  # Note: setup() ends with delay(1800), so the main loop doesn't start
  # polling input until ~t=1800ms. All script times are offset past that.
  shoot idle      $board ""                                                  2500  2700
  shoot menu      $board "A:2200-3000"                                       3300  3500
  shoot settings  $board "A:2200-3000,B:3300-3400"                           3700  3900
  shoot pet       $board "A:2200-2300"                                       2700  2900
  shoot info1     $board "A:2200-2300,A:2600-2700"                           3100  3300
  shoot info2     $board "A:2200-2300,A:2600-2700,B:3000-3100"               3500  3700
  shoot info3     $board "A:2200-2300,A:2600-2700,B:3000-3100,B:3400-3500"   3900  4100
done

echo
echo "Wrote screenshots to $OUT_DIR"
