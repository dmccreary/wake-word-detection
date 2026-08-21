# Shared serial-port discovery. Sourced by upload-code.sh and get-results.sh;
# not meant to be run on its own.
#
# Why this is not just a glob: on macOS every serial device appears TWICE, as
# /dev/cu.NAME and /dev/tty.NAME. They are the same physical port. cu ("call
# up") opens immediately; tty blocks waiting for carrier detect and can hang.
# Globbing both makes one Pico look like two devices. macOS also always has
# cu.Bluetooth-Incoming-Port and cu.debug-console, which are not boards at all.
#
# So we ask mpremote instead. It reports the USB VID:PID of each port, lists
# only the cu.* side on macOS, and gives 0000:0000 for the built-in pseudo
# ports -- which is exactly the signal needed to tell a real board from noise.

# Echoes the chosen port on stdout. All commentary goes to stderr so callers
# can capture the result with PORT="$(find_pico_port)".
find_pico_port() {
    if [[ -n "${PORT:-}" ]]; then
        echo "Using device from PORT environment variable: $PORT" >&2
        echo "$PORT"
        return 0
    fi

    local dev serial vidpid rest
    local -a ports=() labels=()

    while read -r dev serial vidpid rest; do
        [[ -z "$dev" ]] && continue
        # 0000:0000 means "not a real USB serial device" -- Bluetooth, debug
        # console, and other built-ins report this.
        [[ "$vidpid" == "0000:0000" || -z "$vidpid" ]] && continue
        ports+=( "$dev" )
        # The serial number is the ONLY field that distinguishes one Pico from
        # another: identical boards all report 2e8a:0005 with the same
        # description, so without it a multi-board listing is unusable.
        labels+=( "$dev  serial=${serial:-none}  [$vidpid]  ${rest:-unknown}" )
    done < <(mpremote connect list 2>/dev/null)

    if (( ${#ports[@]} == 0 )); then
        echo "Error: No MicroPython board detected." >&2
        echo "Plug the Pico in and try again. If it is plugged in, check that" >&2
        echo "it is not in BOOTSEL mode (it would mount as a USB drive, not a" >&2
        echo "serial port), and that Thonny is not holding the port." >&2
        return 1
    fi

    if (( ${#ports[@]} > 1 )); then
        echo "Multiple MicroPython boards connected; using the FIRST:" >&2
        printf '  %s\n' "${labels[@]}" >&2
        echo "If that is the wrong board, pick one by its serial number:" >&2
        echo "    PORT=${ports[1]} $0" >&2
    fi

    echo "Using device: ${labels[0]}" >&2
    echo "${ports[0]}"
}
