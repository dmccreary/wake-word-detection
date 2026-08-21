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

# A fetched file is not automatically a usable file: an empty or truncated
# calibration.json means the lab was stopped mid-write, and reporting that as
# success would send someone off to analyze nothing.
validate_json() {
    local path="$1"
    if [[ ! -s "$path" ]]; then
        echo "  !! $path is EMPTY -- the lab was stopped before it could" >&2
        echo "     finish writing. Re-run the measurement." >&2
        return 1
    fi
    command -v python3 >/dev/null 2>&1 || return 0
    if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$path" 2>/dev/null; then
        echo "  !! $path is not valid JSON -- truncated write." >&2
        echo "     Re-run the measurement." >&2
        return 1
    fi
    python3 - "$path" <<'PY_SUMMARY'
import json, sys
d = json.load(open(sys.argv[1]))
have = [k for k in ("noise", "speech", "clip", "spectrum") if d.get(k)]
print("     from: %s v%s (config v%s)"
      % (d.get("program", "?"), d.get("version", "?"), d.get("config_version", "?")))
print("     room: %s" % ((d.get("room_note") or "(unset)")[:60]))
print("     measurements: %s" % (", ".join(have) if have else "NONE"))
rec = d.get("recommended")
if rec:
    print("     SPEECH_FLOOR = FULL_SCALE * %.5f  (set by %s)"
          % (rec["speech_floor_fraction"], rec.get("set_by")))
else:
    print("     no recommendation yet -- NOISE and SPEECH are both required")
PY_SUMMARY
    return 0
}

got=0
bad=0
for f in "${FILES[@]}"; do
    echo "Fetching :$f ..."
    # Keep mpremote's stderr: "port in use" and "no such file" are completely
    # different problems, and telling someone to re-run the lab when the real
    # issue is that Thonny still holds the port sends them the wrong way.
    if err="$(mpremote connect "$PORT" cp ":$f" "$RESULTS_DIR/$f" 2>&1)"; then
        echo "  -> $RESULTS_DIR/$f"
        if validate_json "$RESULTS_DIR/$f"; then
            got=$(( got + 1 ))
        else
            bad=$(( bad + 1 ))
        fi
    elif [[ "$err" == *"in use by another program"* ]]; then
        echo >&2
        echo "Error: the serial port is held by another program." >&2
        echo "Thonny keeps the connection open even after you press STOP --" >&2
        echo "quit Thonny (or use Run > Disconnect), then run this again." >&2
        exit 1
    else
        echo "  -- not on the device (run the lab and complete a measurement)"
        echo "     mpremote said: $err"
    fi
done

if (( bad > 0 )); then
    echo >&2
    echo "$bad file(s) came back unusable; see the messages above." >&2
    exit 1
fi

if (( got == 0 )); then
    echo >&2
    echo "Nothing fetched. Run Lab 3 and complete at least one measurement." >&2
    echo "If the port was 'in use by another program', quit Thonny first." >&2
    exit 1
fi

echo
echo "Done. $got file(s) in $SCRIPT_DIR/$RESULTS_DIR/"
