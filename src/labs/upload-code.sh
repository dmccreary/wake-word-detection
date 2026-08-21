#!/usr/bin/env bash
# Upload the smart speaker kit to a connected Raspberry Pi Pico 2 using
# mpremote. Run from anywhere -- the script resolves its own location.
#
# What gets uploaded:
#   lib/*.py            drivers and vendored FFT code  -> :lib/
#   config.py           pin definitions                -> :config.py
#   NN-*.py             each lab program               -> :NN-*.py
#
# config.py and lib/ go first because every lab imports them.
#
# Pass --clean to erase the device first. Useful when the Pico still carries
# files from the prerequisite FFT course and you want its listing to show only
# this kit -- including any stale main.py, which MicroPython auto-runs at boot.
#
# IMPORTANT: Quit (or "Stop/Disconnect" from) Thonny before running this.
# Only one program can use the Pico's serial port at a time. If Thonny is
# connected, mpremote fails with:
#   "failed to access /dev/cu.usbmodem... (it may be in use by another program)"

set -euo pipefail

CLEAN=0
ASSUME_YES=0

usage() {
    cat <<EOF
Usage: ${0##*/} [--clean] [--yes]

  --clean  Erase EVERY file on the Pico before uploading. Any calibration.json
           on the device is copied into results/ first, since it is expensive
           to reproduce -- five seconds per measurement, in one specific room,
           at one specific distance.
  --yes    Skip the confirmation that --clean otherwise requires.
  --help   Show this message.

Force a specific port with:  PORT=/dev/cu.usbmodem101 ${0##*/}
EOF
}

while (( $# > 0 )); do
    case "$1" in
        --clean)   CLEAN=1 ;;
        --yes|-y)  ASSUME_YES=1 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; echo >&2; usage >&2; exit 2 ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v mpremote >/dev/null 2>&1; then
    echo "Error: mpremote is not installed. Install with: pip install mpremote" >&2
    exit 1
fi

echo "NOTE: Quit or disconnect Thonny first -- only one program can use the"
echo "      Pico's serial port at a time."
echo

# Force a specific port with:  PORT=/dev/cu.usbmodem101 ./upload-code.sh
# shellcheck source=find-port.sh
source "$SCRIPT_DIR/find-port.sh"
PORT="$(find_pico_port)"

# Interrupt any running program before copying files.
mpremote connect "$PORT" soft-reset >/dev/null 2>&1 || true

# MicroPython has no recursive delete and mpremote 1.24 has no "rm -r", so the
# directory walk has to run on the device itself. 0x4000 is the ilistdir type
# flag for a directory; anything else is a file.
read -r -d '' DEVICE_WIPE_PY <<'PY' || true
import os
failed = []
def wipe(path):
    try:
        entries = list(os.ilistdir(path))
    except OSError:
        return
    for e in entries:
        full = (path if path != "/" else "") + "/" + e[0]
        if e[1] == 0x4000:
            wipe(full)
            try:
                os.rmdir(full)
            except OSError:
                failed.append(full)
        else:
            try:
                os.remove(full)
            except OSError:
                failed.append(full)
wipe("/")
print("erased; %d item(s) could not be removed" % len(failed))
for f in failed:
    print("  kept:", f)
PY

if (( CLEAN )); then
    echo "--clean: erasing every file on the Pico before uploading."
    echo

    # Rescue results before destroying them.
    mkdir -p results
    if mpremote connect "$PORT" cp :calibration.json \
            results/calibration-before-clean.json >/dev/null 2>&1; then
        echo "  rescued calibration.json -> results/calibration-before-clean.json"
    else
        rmdir results 2>/dev/null || true      # nothing rescued, leave no empty dir
    fi

    # Captured rather than piped: under `set -o pipefail` a failing mpremote
    # in a pipeline would kill the script with no useful message.
    echo "  currently on the device:"
    if ! device_listing="$(mpremote connect "$PORT" ls 2>&1)"; then
        echo >&2
        echo "Error: could not list the device, so nothing was deleted." >&2
        echo "$device_listing" >&2
        echo "If the port is 'in use by another program', quit Thonny." >&2
        exit 1
    fi
    printf '%s\n' "$device_listing" | sed 's/^/    /'

    if (( ! ASSUME_YES )); then
        if [[ ! -t 0 ]]; then
            echo >&2
            echo "Error: --clean needs confirmation but stdin is not a terminal." >&2
            echo "Re-run with --yes if you are sure." >&2
            exit 1
        fi
        echo
        echo "  This CANNOT be undone. The MicroPython firmware is not touched,"
        echo "  only the files -- the board will still boot to a REPL."
        printf "  Type DELETE to continue: "
        read -r reply
        if [[ "$reply" != "DELETE" ]]; then
            echo "Aborted; nothing was deleted." >&2
            exit 1
        fi
    fi

    echo "  erasing..."
    mpremote connect "$PORT" exec "$DEVICE_WIPE_PY"
    echo
fi

upload() {
    local src="$1" dest="$2"
    echo "  -> $dest"
    if ! mpremote connect "$PORT" cp "$src" ":$dest"; then
        echo >&2
        echo "Error: could not write to the Pico." >&2
        echo "If the port is 'in use by another program', QUIT or DISCONNECT" >&2
        echo "Thonny (or any other serial monitor) and run this script again." >&2
        exit 1
    fi
}

shopt -s nullglob
lib_files=( lib/*.py )
lab_files=( [0-9]*.py )
shopt -u nullglob

# 1. Libraries first -- config.py and every lab import these.
if (( ${#lib_files[@]} > 0 )); then
    echo "Uploading ${#lib_files[@]} library file(s) to :lib/ ..."
    mpremote connect "$PORT" mkdir :lib >/dev/null 2>&1 || true
    for f in "${lib_files[@]}"; do
        upload "$f" "lib/$(basename "$f")"
    done
else
    echo "Warning: no library files found in $SCRIPT_DIR/lib/" >&2
fi

# 2. Shared hardware configuration.
if [[ -f config.py ]]; then
    echo "Uploading shared configuration..."
    upload config.py config.py
else
    echo "Warning: config.py not found in $SCRIPT_DIR -- labs will fail to import it." >&2
fi

# 3. Each lab program, flattened to the device root.
if (( ${#lab_files[@]} > 0 )); then
    echo "Uploading ${#lab_files[@]} lab program(s)..."
    for f in "${lab_files[@]}"; do
        upload "$f" "$(basename "$f")"
    done
else
    echo "No lab code found in $SCRIPT_DIR yet."
fi

echo
echo "Done. Files on Pico:"
mpremote connect "$PORT" ls
mpremote connect "$PORT" ls :lib 2>/dev/null || true
