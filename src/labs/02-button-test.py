# Button test -- find out which GPIOs your buttons are actually on.
#
# Written because Lab 3 stopped responding to MODE. When a button produces no
# console line at all, the program never saw a falling edge, and there are only
# a few reasons for that:
#
#   * the button is wired to a different GPIO than config.py claims
#   * only one of the two buttons is connected
#   * both buttons are wired to the same pin
#   * the other leg goes somewhere other than GND, so a press changes nothing
#   * the pin is shorted to GND, so it reads pressed forever
#
# Guessing between those wastes an evening. This tells you.
#
# It watches EVERY free GPIO, not just the two config.py names, so if your
# button is on 13 or 20 it will say so instead of reporting "no press". Pins
# already owned by the display, microphone, speaker, and LED are excluded --
# reconfiguring those as inputs mid-run would break the display this program
# needs in order to talk to you.
#
# Press each button in turn and read the console.

import time

import config

PROGRAM = "02-button-test"
VERSION = "1.0.0"

# Everything config.py has already assigned to something that is not a button.
# Watching these would at best be noise and at worst break the display.
RESERVED = (
    config.SCL_PIN, config.SDA_PIN, config.RES_PIN, config.DC_PIN,
    config.CS_PIN,
    config.MIC_SCK_PIN, config.MIC_WS_PIN, config.MIC_SD_PIN,
    config.SPK_BCK_PIN, config.SPK_WS_PIN, config.SPK_SD_PIN,
)

# GP0..GP22 are the pins broken out on a Pico 2 that can take a button. 23-25
# and 26-29 are either internal or analog-capable pins not on the kit's header.
CANDIDATES = [p for p in range(23)
              if p not in RESERVED and p != config.SPK_ENABLE_PIN]

EXPECTED = {config.BUTTON_MODE_PIN: "MODE", config.BUTTON_SELECT_PIN: "SELECT"}

oled = config.init_display()

# Every candidate gets its own pull-up. An unconnected input with a pull-up
# reads 1 forever; a button to GND reads 0 while held.
from machine import Pin                                    # noqa: E402
watch = {}
for p in CANDIDATES:
    try:
        watch[p] = Pin(p, Pin.IN, Pin.PULL_UP)
    except (ValueError, TypeError):
        pass                                # not a usable GPIO on this board

print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("=" * 58)
print("Button test")
print("=" * 58)
print("config.py expects:  MODE = GPIO %d,  SELECT = GPIO %d"
      % (config.BUTTON_MODE_PIN, config.BUTTON_SELECT_PIN))
print("watching %d pins: %s" % (len(watch), ", ".join(str(p) for p in sorted(watch))))
print()
print("Press each button a few times. Every press prints a line naming the")
print("GPIO it arrived on. Ctrl-C (or STOP) when you are done for a summary.")
print()

# A pin already low at startup is not a press -- it is a wiring fault, and it
# would otherwise be reported as one press and then never again.
stuck = [p for p in sorted(watch) if watch[p].value() == 0]
if stuck:
    print("!! These pins read LOW with nothing pressed: %s"
          % ", ".join(str(p) for p in stuck))
    print("   That is a short to GND, not a button. A pin held low can never")
    print("   produce the 1 -> 0 edge every lab looks for.")
    print()

counts = {p: 0 for p in watch}
last = {p: watch[p].value() for p in watch}
last_ms = {p: 0 for p in watch}
seen_any = False


def draw(msg1, msg2):
    oled.fill(config.BLACK)
    oled.text("Button test", 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)
    oled.text(msg1, 0, 20, config.WHITE)
    oled.text(msg2, 0, 32, config.WHITE)
    oled.text("MODE %d SEL %d" % (config.BUTTON_MODE_PIN,
                                  config.BUTTON_SELECT_PIN),
              0, 52, config.WHITE)
    oled.show()


draw("Press a button", "")

try:
    while True:
        now = time.ticks_ms()
        for p in watch:
            v = watch[p].value()
            if last[p] == 1 and v == 0:
                if time.ticks_diff(now, last_ms[p]) > config.DEBOUNCE_MS:
                    counts[p] += 1
                    last_ms[p] = now
                    seen_any = True
                    role = EXPECTED.get(p)
                    if role:
                        print("GPIO %-2d pressed  <- this is %s, as configured"
                              % (p, role))
                        draw("GPIO %d = %s" % (p, role), "count %d" % counts[p])
                    else:
                        print("GPIO %-2d pressed  <- NOT in config.py!" % p)
                        draw("GPIO %d" % p, "not configured!")
            last[p] = v
        time.sleep_ms(5)

except KeyboardInterrupt:
    print()
    print("=" * 58)
    print("SUMMARY")
    print("=" * 58)
    if not seen_any:
        print("No presses detected on ANY pin.")
        print()
        print("Every watched pin stayed at 1 the whole time, so nothing ever")
        print("pulled one to GND. Check that each button's other leg actually")
        print("goes to a GND pin -- a button wired between two GPIOs, or to")
        print("3V3, cannot produce the falling edge the labs look for.")
    else:
        pressed_pins = [p for p in sorted(counts) if counts[p]]
        for p in pressed_pins:
            role = EXPECTED.get(p, "not in config.py")
            print("  GPIO %-2d  %3d press(es)   %s" % (p, counts[p], role))
        print()
        for pin, role in sorted(EXPECTED.items()):
            if counts.get(pin, 0) == 0:
                print("!! %s (GPIO %d) never registered a press." % (role, pin))
        unexpected = [p for p in pressed_pins if p not in EXPECTED]
        if unexpected:
            print()
            print("Buttons responded on %s, which config.py does not use."
                  % ", ".join("GPIO %d" % p for p in unexpected))
            print("Either re-wire to GPIO %d and %d, or edit config.py:"
                  % (config.BUTTON_MODE_PIN, config.BUTTON_SELECT_PIN))
            print("    BUTTON_MODE_PIN = %d" % unexpected[0])
            if len(unexpected) > 1:
                print("    BUTTON_SELECT_PIN = %d" % unexpected[1])
            print("then re-run ./upload-code.sh.")
        elif len(pressed_pins) == 1 and len(EXPECTED) == 2:
            print()
            print("Only one pin ever responded. If you pressed both buttons,")
            print("they are wired to the same GPIO -- which is why one of them")
            print("appears to do nothing.")
    oled.fill(config.BLACK)
    oled.text("Stopped.", 30, 28, config.WHITE)
    oled.show()
