# Button test -- prove which detection mechanism actually works, per pin.
#
# v2.0.0 exists because of a specific failure: GPIO 15 (SELECT) responds, GPIO
# 14 (MODE) does not, yet a plain polling scan says BOTH pins are wired
# correctly. Those two facts together mean the problem is not the wiring and
# not the button -- it is the mechanism used to notice the press.
#
# So this watches each pin BOTH WAYS AT ONCE and counts them separately:
#
#   IRQ  -- a falling-edge interrupt. Fires whenever the press physically
#           happens, even while the program is busy elsewhere.
#   POLL -- reading pin.value() in a loop and looking for 1 -> 0. Only sees a
#           press if the loop happens to be looking at the time.
#
# Four outcomes, each with a different fix:
#
#   both counts rise on both pins  -> hardware and IRQs are fine, the bug is in
#                                     whatever the lab does between polls
#   IRQ 0 but POLL rises on a pin  -> that pin's interrupt is not being
#                                     delivered; the labs must not rely on it
#   POLL 0 but IRQ rises           -> the press is shorter than the poll
#                                     interval; polling alone will always miss it
#   both 0 on a pin                -> wiring after all
#
# Press MODE several times, then SELECT several times, then stop.

import time
from machine import Pin

import config

PROGRAM = "02-button-test"
VERSION = "2.0.0"

button_mode, button_select = config.init_buttons()
oled = config.init_display()

PINS = {"MODE": button_mode, "SELECT": button_select}
NUM = {"MODE": config.BUTTON_MODE_PIN, "SELECT": config.BUTTON_SELECT_PIN}

irq_count = {"MODE": 0, "SELECT": 0}
poll_count = {"MODE": 0, "SELECT": 0}
last_level = {"MODE": 1, "SELECT": 1}
irq_error = {}


def make_handler(name):
    """One IRQ handler per button. Counting only -- no allocation."""
    def handler(pin):
        irq_count[name] += 1
    return handler


print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("=" * 60)
print("Button test -- IRQ vs polling, measured separately")
print("=" * 60)

for name in ("MODE", "SELECT"):
    try:
        PINS[name].irq(trigger=Pin.IRQ_FALLING, handler=make_handler(name))
        print("  %-6s GPIO %-2d  IRQ registered" % (name, NUM[name]))
    except Exception as e:            # noqa: BLE001 -- report anything at all
        irq_error[name] = repr(e)
        print("  %-6s GPIO %-2d  IRQ REGISTRATION FAILED: %r"
              % (name, NUM[name], e))

print()
print("Resting levels (1 = not pressed): %s"
      % ", ".join("%s=%d" % (n, PINS[n].value()) for n in PINS))
print()
print("Press MODE a few times, then SELECT a few times.")
print("Each line shows which mechanism noticed it. Ctrl-C for the summary.")
print()

reported = {"MODE": (0, 0), "SELECT": (0, 0)}


def draw():
    oled.fill(config.BLACK)
    oled.text("Button test 2.0", 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)
    oled.text("MODE i%d p%d" % (irq_count["MODE"], poll_count["MODE"]),
              0, 20, config.WHITE)
    oled.text("SEL  i%d p%d" % (irq_count["SELECT"], poll_count["SELECT"]),
              0, 32, config.WHITE)
    oled.text("i=irq p=poll", 0, 52, config.WHITE)
    oled.show()


draw()
last_draw = time.ticks_ms()
last_edge_ms = {"MODE": 0, "SELECT": 0}

try:
    while True:
        now = time.ticks_ms()

        for name in ("MODE", "SELECT"):
            v = PINS[name].value()
            if last_level[name] == 1 and v == 0:
                if time.ticks_diff(now, last_edge_ms[name]) > config.DEBOUNCE_MS:
                    poll_count[name] += 1
                    last_edge_ms[name] = now
            last_level[name] = v

            # Report whenever either counter for this button moves, naming
            # which mechanism saw it. A press caught by only one is the whole
            # point of this program.
            if (irq_count[name], poll_count[name]) != reported[name]:
                di = irq_count[name] - reported[name][0]
                dp = poll_count[name] - reported[name][1]
                if di and dp:
                    how = "IRQ + POLL (both)"
                elif di:
                    how = "IRQ only  <- polling missed it"
                else:
                    how = "POLL only <- the interrupt did NOT fire"
                print("%-6s GPIO %-2d  %s   (irq=%d poll=%d)"
                      % (name, NUM[name], how, irq_count[name], poll_count[name]))
                reported[name] = (irq_count[name], poll_count[name])
                draw()

        if time.ticks_diff(now, last_draw) > 500:
            last_draw = now
            draw()
        time.sleep_ms(5)

except KeyboardInterrupt:
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("  %-6s %-6s %8s %8s" % ("button", "gpio", "IRQ", "POLL"))
    for name in ("MODE", "SELECT"):
        print("  %-6s %-6d %8d %8d"
              % (name, NUM[name], irq_count[name], poll_count[name]))
    print()

    for name in ("MODE", "SELECT"):
        i, p = irq_count[name], poll_count[name]
        if name in irq_error:
            print("%s: IRQ could not even be registered (%s)."
                  % (name, irq_error[name]))
        elif p and not i:
            print("%s (GPIO %d): the button works, but its INTERRUPT never"
                  % (name, NUM[name]))
            print("   fired. Any lab that relies on an IRQ for this pin will")
            print("   appear dead. The labs need to poll this pin instead.")
        elif i and not p:
            print("%s (GPIO %d): interrupt fires but polling never caught it"
                  % (name, NUM[name]))
            print("   -- presses are shorter than the poll interval.")
        elif not i and not p:
            print("%s (GPIO %d): no presses detected at all. Either it was not"
                  % (name, NUM[name]))
            print("   pressed, or its other leg does not reach GND.")
        else:
            print("%s (GPIO %d): both mechanisms work." % (name, NUM[name]))

    oled.fill(config.BLACK)
    oled.text("Stopped.", 30, 28, config.WHITE)
    oled.show()
