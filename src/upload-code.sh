#!/usr/bin/env bash
# Upload the smart speaker kit to a connected Raspberry Pi Pico 2 using
# mpremote. Run from anywhere -- the script resolves its own location.
#
# What gets uploaded:
#   lib/*.py            drivers and vendored FFT code  -> :lib/
#   config.py           pin definitions                -> :config.py
#   labs/NN-*/NN-*.py   each lab program               -> :NN-*.py
#
# config.py and lib/ go first because every lab imports them.
#
# IMPORTANT: Quit (or "Stop/Disconnect" from) Thonny before running this.
# Only one program can use the Pico's serial port at a time. If Thonny is
# connected, mpremote fails with:
#   "failed to access /dev/cu.usbmodem... (it may be in use by another program)"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v mpremote >/dev/null 2>&1; then
    echo "Error: mpremote is not installed. Install with: pip install mpremote" >&2
    exit 1
fi

echo "NOTE: Quit or disconnect Thonny first -- only one program can use the"
echo "      Pico's serial port at a time."
echo

# We pass the exact serial port to mpremote rather than using "connect auto",
# which only matches a fixed list of vendor/product IDs and silently reports
# "no device found" for boards it does not recognize.
#
# Force a specific port with:  PORT=/dev/cu.usbmodem14301 ./upload-code.sh
if [[ -n "${PORT:-}" ]]; then
    echo "Using device from PORT environment variable: $PORT"
else
    shopt -s nullglob
    serial_devs=(
        /dev/cu.usbmodem*
        /dev/tty.usbmodem*
        /dev/ttyACM*
        /dev/ttyUSB*
    )
    shopt -u nullglob
    if (( ${#serial_devs[@]} == 0 )); then
        echo "Error: No Pico detected (no usbmodem/ttyACM/ttyUSB device)." >&2
        echo "Plug it in and try again." >&2
        exit 1
    fi
    PORT="${serial_devs[0]}"
    if (( ${#serial_devs[@]} > 1 )); then
        echo "Multiple serial devices found; using the first:"
        printf '  %s\n' "${serial_devs[@]}"
        echo "Override with: PORT=/dev/your-device ./upload-code.sh"
    fi
    echo "Using device: $PORT"
fi

# Interrupt any running program before copying files.
mpremote connect "$PORT" soft-reset >/dev/null 2>&1 || true

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
lab_files=( labs/*/[0-9]*.py )
shopt -u nullglob

# 1. Libraries first -- config.py and every lab import these.
if (( ${#lib_files[@]} > 0 )); then
    echo "Uploading ${#lib_files[@]} library file(s) to :lib/ ..."
    mpremote connect "$PORT" mkdir :lib >/dev/null 2>&1 || true
    for f in "${lib_files[@]}"; do
        upload "$f" "lib/$(basename "$f")"
    done
fi

# 2. Shared hardware configuration.
if [[ -f config.py ]]; then
    echo "Uploading shared configuration..."
    upload config.py config.py
fi

# 3. Each lab program, flattened to the device root.
if (( ${#lab_files[@]} > 0 )); then
    echo "Uploading ${#lab_files[@]} lab program(s)..."
    for f in "${lab_files[@]}"; do
        upload "$f" "$(basename "$f")"
    done
else
    echo "No lab code found under labs/*/ yet."
fi

echo
echo "Done. Files on Pico:"
mpremote connect "$PORT" ls
mpremote connect "$PORT" ls :lib 2>/dev/null || true
