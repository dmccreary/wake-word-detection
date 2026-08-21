# Lab 1: Setup -- prove every part of the kit works before building on it.
#
# This lab does nothing clever. It exists so that when Lab 4 fails to hear a
# wake word, you already know for certain the microphone works, and can go
# looking for the bug somewhere useful.
#
# It also introduces the pattern every later lab uses: nothing here knows a pin
# number. Every peripheral comes from config.py, so re-wiring the kit means
# editing one file instead of twenty.
#
# Press MODE to step through the checks. In the Speaker check, UP and DOWN
# change the volume -- the same up/down pair Lab 4 reuses for the detection
# threshold.

import time

import config

CHECKS = ["LED", "Display", "Buttons", "Microphone", "Speaker"]

oled = config.init_display()
led = config.init_led()
button_mode, button_up, button_down = config.init_buttons()
amp_enable = config.init_amp_enable()

check = 0
volume = config.DEFAULT_VOLUME
press_count = 0
mic_peak = 0

# The microphone and speaker are opened on demand rather than up front. Both
# claim an I2S peripheral, and holding one open while it is not in use is a
# habit worth not forming on a chip with only two.
mic = None
speaker = None

last = [button_mode.value(), button_up.value(), button_down.value()]
last_press_ms = time.ticks_ms()


def pressed(pin, previous):
    """True on the falling edge -- the moment the button goes 1 -> 0."""
    return previous == 1 and pin.value() == 0


def close_peripherals():
    global mic, speaker
    if mic is not None:
        mic.deinit()
        mic = None
    if speaker is not None:
        speaker.deinit()
        speaker = None


def draw(line2="", line3="", line4=""):
    oled.fill(config.BLACK)
    oled.text("Lab 1: Setup", 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)
    oled.text("%d/%d %s" % (check + 1, len(CHECKS), CHECKS[check]), 0, 16,
              config.WHITE)
    oled.text(line2, 0, 28, config.WHITE)
    oled.text(line3, 0, 38, config.WHITE)
    oled.text(line4, 0, 48, config.WHITE)
    oled.text("MODE=next", 0, 56, config.WHITE)
    oled.show()


def check_led():
    """Blink the onboard LED. Proves code is running at all."""
    led.toggle()
    draw("Onboard LED", "blinking 1 Hz", "state: %d" % led.value())


def check_display():
    """Draw shapes. Proves the SPI wiring and the framebuffer."""
    oled.fill(config.BLACK)
    oled.text("Lab 1: Setup", 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)
    oled.text("2/5 Display", 0, 16, config.WHITE)
    oled.rect(4, 28, 40, 24, config.WHITE)
    oled.fill_rect(52, 28, 40, 24, config.WHITE)
    oled.line(96, 28, 124, 52, config.WHITE)
    oled.text("MODE=next", 0, 56, config.WHITE)
    oled.show()


def check_buttons():
    """Report which buttons are held. Proves all three are wired and pulled up.

    PULL_UP means an unpressed button reads 1, so "down" here means value 0.
    """
    held = ""
    held += "U" if button_up.value() == 0 else "-"
    held += "D" if button_down.value() == 0 else "-"
    draw("UP/DOWN held:", "   %s" % held, "presses: %d" % press_count)


def check_microphone():
    """Capture 256 samples and report peak swing. Proves the mic hears."""
    global mic, mic_peak
    if mic is None:
        mic = config.init_microphone()
        # The mic needs a moment to settle after power-up; the first reads are
        # garbage, so throw them away.
        settle = bytearray(256 * 4)
        for _ in range(5):
            mic.readinto(settle)
            time.sleep_ms(20)

    raw = bytearray(256 * 4)
    samples = config.read_samples(mic, raw, 256)
    mic_peak = max(abs(s) for s in samples)
    pct = mic_peak / config.FULL_SCALE * 100

    bar = int(min(1.0, pct / 20) * (config.WIDTH - 4))
    draw("Make a noise", "peak %.2f%% FS" % pct)
    oled.rect(0, 46, config.WIDTH, 8, config.WHITE)
    if bar > 0:
        oled.fill_rect(2, 48, bar, 4, config.WHITE)
    oled.show()


def check_speaker():
    """Play a short beep. UP/DOWN change the volume it plays at."""
    global speaker
    if speaker is None:
        speaker = config.init_speaker()
    draw("UP/DOWN volume", "volume: %d/%d" % (volume, config.VOLUME_STEPS),
         "beeping...")
    config.play_tone(speaker, 880, 120, volume)


RUNNERS = [check_led, check_display, check_buttons, check_microphone,
           check_speaker]

print("Lab 1: Setup. MODE steps through checks, UP/DOWN adjust volume.")
print("Checks:", ", ".join(CHECKS))
draw("Starting...")

try:
    while True:
        now = time.ticks_ms()
        settled = time.ticks_diff(now, last_press_ms) > config.DEBOUNCE_MS

        if settled and pressed(button_mode, last[0]):
            close_peripherals()
            check = (check + 1) % len(CHECKS)
            last_press_ms = now
            print("check ->", CHECKS[check])

        if settled and pressed(button_up, last[1]):
            press_count += 1
            volume = min(config.VOLUME_STEPS, volume + 1)
            last_press_ms = now
            print("volume ->", volume)

        if settled and pressed(button_down, last[2]):
            press_count += 1
            volume = max(0, volume - 1)
            last_press_ms = now
            print("volume ->", volume)

        last = [button_mode.value(), button_up.value(), button_down.value()]

        RUNNERS[check]()

        # The speaker check already takes ~120 ms playing its beep, and the
        # microphone check spends its time blocked in readinto(). The others
        # need a deliberate pause so the LED blinks at a visible rate.
        if check in (0, 1, 2):
            time.sleep_ms(200)

except KeyboardInterrupt:
    close_peripherals()
    oled.fill(config.BLACK)
    oled.text("Stopped.", 30, 28, config.WHITE)
    oled.show()
    print("Stopped.")
