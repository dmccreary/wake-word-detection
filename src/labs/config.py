# Hardware configuration for the smart speaker kit.
#
# CONFIG_VERSION is printed by every lab. Bump the MAJOR when a change would
# make an existing lab misbehave rather than merely differ -- moving a pin, for
# instance, which is exactly what the drop from three buttons to two did.
#
# Every lab in this course imports this file instead of repeating pin numbers,
# so the whole kit is described in exactly one place. This is the same pattern
# the prerequisite course (Real-Time DSP on a $5 Microcontroller) used, extended
# with the thing that course did not have: an audio OUTPUT path.
#
# Everything here runs on a plain Pico 2. The Pico 2 W's radio is not touched
# until the networking labs.

CONFIG_VERSION = "2.2.0"        # 2.2.0: latch_buttons() polls as well as IRQs

from machine import Pin, SPI, I2S
import math
import struct
import time
import ssd1306

WIDTH = 128
HEIGHT = 64

WHITE = 1
BLACK = 0

# --- Display: 2.42" SSD1306/SSD1309 128x64 OLED over SPI -------------------
# Unchanged from the prerequisite course's kit.
#
# The 2.42" module is preferred over the common 0.96"/1.3" ones. All three are
# 128x64 with the same pinout and driver, so nothing below changes -- you are
# buying legibility, not capability. This device is meant to be glanced at from
# across a room, not read at 30 cm like a bench instrument.
SCL_PIN = 2
SDA_PIN = 3
RES_PIN = 4
DC_PIN = 5
CS_PIN = 6

# --- Buttons ----------------------------------------------------------------
# Three momentary push buttons, up from the prerequisite course's two. Each
# button's other leg goes to GND, and PULL_UP holds the pin at 1 until a press
# pulls it to 0 -- so a press is a FALLING edge.
#
# The kit has TWO buttons, and every lab uses them the same way:
#
#   MODE   (GPIO 14)  cycles the program's state
#   SELECT (GPIO 15)  acts within the current state
#
# SELECT does whatever the current mode says: run this test, enroll this
# template, or step a value. Values WRAP rather than needing a second button --
# volume runs 0..VOLUME_STEPS and back to 0, the Lab 4 threshold runs up to
# 0.99 and back to 0.30. Anything destructive (clearing measurements, forgetting
# a template) gets its own MODE position instead, so it takes a deliberate walk
# through the mode list and can never fire from a stray press.
BUTTON_MODE_PIN = 14
BUTTON_SELECT_PIN = 15

DEBOUNCE_MS = 50

# --- Microphone: INMP441 I2S MEMS mic (I2S peripheral 0, RX) ----------------
# Unchanged from the prerequisite course.
MIC_SCK_PIN = 10  # Serial clock
MIC_WS_PIN = 11   # Word select
MIC_SD_PIN = 12   # Serial data

# The INMP441 sends 24 real bits of audio inside a 32-bit word, so we read
# 32-bit samples and shift right by 8 to recover the value.
MIC_I2S_ID = 0
MIC_SAMPLE_BITS = 32
SAMPLE_RATE = 12800
MIC_BUFFER_BYTES = 40000

FULL_SCALE = 8388608  # 2^23, the largest magnitude a 24-bit sample can hold

# --- Microphone calibration (measure this yourself in Lab 3) ----------------
# SPEECH_FLOOR is the loudness gate that separates "someone is talking" from
# "the room is just sitting there". Lab 4's detector uses it so that silence
# cannot match silence -- normalized noise correlates with normalized noise
# perfectly well, so score alone is not enough.
#
# The default below is a starting point for an ordinary quiet room, NOT a
# universal constant. Lab 3 measures your actual noise floor and speaking level
# and prints a value to paste here. A floor that is too high reads as "the
# detector cannot hear me"; too low, and room noise scores against the
# template all day.
#
# The INMP441 is specified at -26 dBFS for a 94 dB SPL input, which makes the
# conversion dBFS = SPL - 120. The default works out to roughly 58 dB SPL:
# above a quiet office, below conversation at a metre.
SPEECH_FLOOR = FULL_SCALE * 0.0008

# INMP441 sensitivity, used to turn a measured level into an estimated sound
# pressure level. Nominal from the datasheet -- units vary by about +/-1 dB and
# nothing here is acoustically calibrated, so treat any SPL figure as an
# estimate rather than a measurement.
MIC_DBFS_AT_94DB_SPL = -26.0
SPL_OFFSET = 94.0 - MIC_DBFS_AT_94DB_SPL   # dBFS + SPL_OFFSET = estimated dB SPL

# --- Speaker: MAX98357A I2S class-D amplifier (I2S peripheral 1, TX) --------
# New in this course. The RP2350 has two I2S peripherals, so the microphone can
# keep peripheral 0 for capture while the amplifier takes peripheral 1 for
# playback -- they run independently and at different sample rates.
SPK_BCK_PIN = 16  # Bit clock      -> MAX98357A BCLK
SPK_WS_PIN = 17   # Word select    -> MAX98357A LRC
SPK_SD_PIN = 18   # Serial data    -> MAX98357A DIN

# The MAX98357A's own SD pin is a shutdown/gain-select input. Wiring it to a
# GPIO lets software shut the amplifier off completely, which is exactly the
# hardware half of the mute-and-resume self-trigger mitigation this course
# builds later. Leave it unconnected and set this to None for default gain.
SPK_ENABLE_PIN = 19

SPK_I2S_ID = 1
SPK_SAMPLE_BITS = 16
PLAYBACK_RATE = 16000       # what cloud text-to-speech typically returns
SPK_BUFFER_BYTES = 20000

VOLUME_STEPS = 10
DEFAULT_VOLUME = 5


def init_led():
    # The onboard LED is GPIO 25 on a plain Pico 2, but on a Pico 2 W it is
    # driven by the wireless chip and only reachable by the name "LED".
    try:
        return Pin("LED", Pin.OUT)
    except (ValueError, TypeError):
        return Pin(25, Pin.OUT)


def init_display():
    spi = SPI(0, sck=Pin(SCL_PIN), mosi=Pin(SDA_PIN))
    return ssd1306.SSD1306_SPI(WIDTH, HEIGHT, spi,
                               Pin(DC_PIN), Pin(RES_PIN), Pin(CS_PIN))


def init_buttons():
    """The two buttons, in the order (mode, select)."""
    return (Pin(BUTTON_MODE_PIN, Pin.IN, Pin.PULL_UP),
            Pin(BUTTON_SELECT_PIN, Pin.IN, Pin.PULL_UP))


def latch_buttons(mode_pin, select_pin):
    """Record button presses reliably. Returns (took, poll).

    Two mechanisms, deliberately, because neither is sufficient alone:

      * An interrupt catches a press the instant it happens, even while the
        program is blocked doing something else. But an interrupt that fails to
        fire -- for any reason, on any one pin -- fails SILENTLY, and the
        symptom is a button that does nothing while its neighbour works.

      * Polling always works, because it just reads the pin. But it only sees a
        press while the loop is actually looking, and these labs stop looking
        for seconds at a time during a measurement.

    Used together they cover each other. The interrupt catches presses during
    blocking work; the polling catches presses the interrupt missed. A press is
    latched by whichever notices first, and the debounce timestamp stops the
    two from counting the same press twice.

    Long-running code should call poll() periodically -- once per frame is
    plenty -- so a press made during a measurement is not lost.
    """
    pins = {"mode": mode_pin, "select": select_pin}
    flags = {"mode": False, "select": False}
    last_ms = {"mode": 0, "select": 0}
    level = {"mode": mode_pin.value(), "select": select_pin.value()}

    def record(name):
        # Shared by both mechanisms, so a press seen by the interrupt AND by
        # the next poll still counts once. Mechanical contacts also bounce for
        # a few milliseconds, which this same window absorbs.
        now = time.ticks_ms()
        if time.ticks_diff(now, last_ms[name]) < DEBOUNCE_MS:
            return
        last_ms[name] = now
        flags[name] = True

    def make(name):
        def handler(pin):
            record(name)            # kept allocation-free for IRQ context
        return handler

    for name in pins:
        try:
            pins[name].irq(trigger=Pin.IRQ_FALLING, handler=make(name))
        except (AttributeError, ValueError, OSError, TypeError):
            pass                    # no interrupt here; polling carries it

    def poll():
        """Edge-detect by reading the pins. Safe to call as often as you like.

        Because `level` persists across calls, a press that began while the
        program was busy is still caught, as long as the button is still down
        when polling resumes.
        """
        for name in pins:
            v = pins[name].value()
            if level[name] == 1 and v == 0:
                record(name)
            level[name] = v

    def took(name):
        """Consume one latched press of `name`, if one is waiting."""
        poll()
        if flags[name]:
            flags[name] = False
            return True
        return False

    return took, poll


def init_microphone(rate=SAMPLE_RATE):
    return I2S(MIC_I2S_ID,
               sck=Pin(MIC_SCK_PIN), ws=Pin(MIC_WS_PIN), sd=Pin(MIC_SD_PIN),
               mode=I2S.RX, bits=MIC_SAMPLE_BITS, format=I2S.MONO,
               rate=rate, ibuf=MIC_BUFFER_BYTES)


def init_speaker(rate=PLAYBACK_RATE):
    return I2S(SPK_I2S_ID,
               sck=Pin(SPK_BCK_PIN), ws=Pin(SPK_WS_PIN), sd=Pin(SPK_SD_PIN),
               mode=I2S.TX, bits=SPK_SAMPLE_BITS, format=I2S.MONO,
               rate=rate, ibuf=SPK_BUFFER_BYTES)


def init_amp_enable():
    """The amplifier's shutdown pin, or None if it isn't wired up."""
    if SPK_ENABLE_PIN is None:
        return None
    return Pin(SPK_ENABLE_PIN, Pin.OUT, value=1)


def read_samples(mic, raw, count):
    """Read `count` samples off the mic and return them DC-removed.

    Three things trip up almost everyone, and all three are handled here:
      1. Samples arrive as 32-bit words but only the top 24 bits are audio,
         so we shift right by 8.
      2. There is a DC offset -- the numbers sit above or below zero even in
         silence. Sound is the WOBBLE, not the value, so we subtract the mean.
      3. readinto() can return a short read, so we use what actually arrived.
    """
    n = mic.readinto(raw)
    words = struct.unpack("<%di" % (n // 4), raw[:n])
    samples = [w >> 8 for w in words]
    dc = sum(samples) / len(samples)
    return [s - dc for s in samples]


def dbfs(rms):
    """Level in dBFS. Full scale is 0 dB, and every value below it is negative.

    Returns -120.0 for silence rather than raising on log(0).
    """
    if rms <= 0:
        return -120.0
    return 20.0 * math.log(rms / FULL_SCALE) / 2.302585092994046


def spl(rms):
    """Estimated dB SPL from a measured level. See MIC_DBFS_AT_94DB_SPL."""
    return dbfs(rms) + SPL_OFFSET


def tone_buffer(freq, ms, volume=DEFAULT_VOLUME, rate=PLAYBACK_RATE):
    """One buffer of a sine wave, as signed 16-bit mono samples.

    volume is 0..VOLUME_STEPS and scales amplitude linearly. Amplitude tops out
    at 30000 rather than 32767 to leave headroom against clipping.
    """
    count = int(rate * ms / 1000)
    amplitude = int(30000 * volume / VOLUME_STEPS)
    buf = bytearray(count * 2)
    step = 2 * math.pi * freq / rate
    for i in range(count):
        struct.pack_into("<h", buf, i * 2, int(amplitude * math.sin(step * i)))
    return buf


def play_tone(speaker, freq, ms, volume=DEFAULT_VOLUME, rate=PLAYBACK_RATE):
    speaker.write(tone_buffer(freq, ms, volume, rate))
