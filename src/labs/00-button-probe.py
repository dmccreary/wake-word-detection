# Probe: does the microphone break the MODE button?
#
# The evidence so far is contradictory. 02-button-test.py sees GPIO 14 fine.
# Lab 3 polls the same pin the same way and never sees it. The one thing Lab 3
# does that the button test does not is open the I2S microphone.
#
# So this runs the SAME loop twice, with only that difference:
#
#   Phase 1  display + buttons only          <- what 02-button-test does
#   Phase 2  display + buttons + MICROPHONE  <- what Lab 3 does
#
# Press MODE several times in each phase. If GPIO 14 responds in phase 1 and
# goes dead in phase 2, the microphone is the cause and we stop looking
# anywhere else. If it responds in both, the fault is in Lab 3's own logic.
# If it responds in neither, the earlier button test result was a fluke.
#
# Every raw level change is printed, so this cannot be fooled by the latching
# layer -- it reports what the pin itself is doing.

import time

import config

PROGRAM = "00-button-probe"
VERSION = "1.0.0"

oled = config.init_display()
button_mode, button_select = config.init_buttons()

MODE_PIN = config.BUTTON_MODE_PIN
SEL_PIN = config.BUTTON_SELECT_PIN


def banner(phase, note):
    oled.fill(config.BLACK)
    oled.text("Button probe", 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)
    oled.text("Phase %d" % phase, 0, 18, config.WHITE)
    oled.text(note, 0, 30, config.WHITE)
    oled.text("MODE x5 then SEL", 0, 52, config.WHITE)
    oled.show()


def watch(phase, note):
    """Report every raw transition on both pins until SELECT ends the phase."""
    print()
    print("-" * 58)
    print("PHASE %d: %s" % (phase, note))
    print("-" * 58)
    print("Press MODE several times. Then press SELECT to finish this phase.")
    print()
    banner(phase, note)

    edges = {MODE_PIN: 0, SEL_PIN: 0}
    level = {MODE_PIN: button_mode.value(), SEL_PIN: button_select.value()}
    print("resting levels: GPIO%d=%d  GPIO%d=%d"
          % (MODE_PIN, level[MODE_PIN], SEL_PIN, level[SEL_PIN]))

    last_beat = time.ticks_ms()
    while True:
        now = time.ticks_ms()
        for pin, num in ((button_mode, MODE_PIN), (button_select, SEL_PIN)):
            v = pin.value()
            if v != level[num]:
                print("  GPIO %-2d  %d -> %d" % (num, level[num], v))
                if level[num] == 1 and v == 0:
                    edges[num] += 1
                level[num] = v

        # SELECT is the phase terminator, but only once it has been released,
        # so the same press cannot immediately end the next phase too.
        if edges[SEL_PIN] > 0 and level[SEL_PIN] == 1:
            break

        # Proof the loop is alive even when nothing is happening. Without this
        # a dead pin and a dead program look identical.
        if time.ticks_diff(now, last_beat) > 3000:
            last_beat = now
            print("  ...alive, GPIO%d=%d GPIO%d=%d, MODE edges so far: %d"
                  % (MODE_PIN, level[MODE_PIN], SEL_PIN, level[SEL_PIN],
                     edges[MODE_PIN]))
        time.sleep_ms(5)

    print()
    print("PHASE %d RESULT: MODE (GPIO %d) falling edges = %d"
          % (phase, MODE_PIN, edges[MODE_PIN]))
    return edges[MODE_PIN]


print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("=" * 58)
print("Does opening the microphone stop GPIO %d responding?" % MODE_PIN)
print("=" * 58)

before = watch(1, "no microphone")

print()
print("Opening the I2S microphone now (this is the only change)...")
mic = config.init_microphone()
print("microphone open.")

after = watch(2, "microphone OPEN")

print()
print("=" * 58)
print("VERDICT")
print("=" * 58)
print("  MODE edges without microphone: %d" % before)
print("  MODE edges with microphone   : %d" % after)
print()
if before > 0 and after == 0:
    print("The microphone is the cause. Opening I2S stops GPIO %d from" % MODE_PIN)
    print("registering, which is why Lab 3 ignores MODE while 02-button-test")
    print("sees it. The fix belongs in how the mic is configured, not in the")
    print("button code.")
elif before > 0 and after > 0:
    print("The pin works in both phases, microphone or not. The fault is in")
    print("Lab 3's own button handling, not the hardware and not the mic.")
elif before == 0 and after == 0:
    print("GPIO %d never registered a press in either phase. The earlier" % MODE_PIN)
    print("02-button-test result does not reproduce -- suspect an intermittent")
    print("connection on that button.")
else:
    print("MODE responded only with the microphone open, which makes no sense")
    print("and points at an intermittent connection.")

try:
    mic.deinit()
except Exception:
    pass
