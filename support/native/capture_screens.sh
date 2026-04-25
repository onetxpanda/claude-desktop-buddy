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
  shoot idle      $board ""                                                 2300 2500
  shoot menu      $board "A:500-1300"                                       1900 2100
  shoot settings  $board "A:500-1300,B:1500-1550"                           2100 2300
  shoot pet       $board "A:500-550"                                        1200 1400
  shoot info1     $board "A:500-550,A:900-950"                              1500 1700
  shoot info2     $board "A:500-550,A:900-950,B:1300-1350"                  2000 2200
  shoot info3     $board "A:500-550,A:900-950,B:1300-1350,B:1800-1850"      2500 2700
done

echo
echo "Wrote screenshots to $OUT_DIR"
