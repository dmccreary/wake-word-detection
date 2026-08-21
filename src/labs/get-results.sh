#!/usr/bin/env bash
# Copy calibration.json (and any other results) off a connected Pico 2.
#
# Lab 3 writes calibration.json to the Pico's own flash after every
# measurement. This pulls it back to results/ next to this script so it can be
# committed, compared between rooms, or handed to someone else to read.
#
# IMPORTANT: Quit (or "Stop/Disconnect" from) Thonny before running this --
# only one program can use the Pico's serial port at a time.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RESULTS_DIR="results"
FILES=( calibration.json )

if ! command -v mpremote >/dev/null 2>&1; then
    echo "Error: mpremote is not installed. Install with: pip install mpremote" >&2
    exit 1
fi

# Force a specific port with:  PORT=/dev/cu.usbmodem101 ./get-results.sh
# shellcheck source=find-port.sh
source "$SCRIPT_DIR/find-port.sh"
PORT="$(find_pico_port)"

mkdir -p "$RESULTS_DIR"

got=0
for f in "${FILES[@]}"; do
    echo "Fetching :$f ..."
    if mpremote connect "$PORT" cp ":$f" "$RESULTS_DIR/$f" 2>/dev/null; then
        echo "  -> $RESULTS_DIR/$f"
        got=$(( got + 1 ))
    else
        echo "  -- not on the device yet (run the lab first)"
    fi
done

if (( got == 0 )); then
    echo >&2
    echo "Nothing fetched. Run Lab 3 and complete at least one measurement." >&2
    echo "If the port was 'in use by another program', quit Thonny first." >&2
    exit 1
fi

echo
echo "Done. $got file(s) in $SCRIPT_DIR/$RESULTS_DIR/"
