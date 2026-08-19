# Hardware configuration for the smart speaker kit.
#
# Every lab in this course imports this file instead of repeating pin numbers,
# so the whole kit is described in exactly one place. This is the same pattern
# the prerequisite course (Real-Time DSP on a $5 Microcontroller) used, extended
# with the two things that course did not have: an audio OUTPUT path and a third
# button.
#
# Everything here runs on a plain Pico 2. The Pico 2 W's radio is not touched
# until the networking labs.

from machine import Pin, SPI, I2S
import math
import struct
import ssd1306

WIDTH = 128
HEIGHT = 64

WHITE = 1
BLACK = 0

# --- Display: SSD1306 128x64 OLED over SPI ---------------------------------
# Unchanged from the prerequisite course's kit.
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
# MODE cycles the program's state; UP/DOWN adjust whatever the current mode
# says is adjustable (volume in Lab 1, detection threshold in Lab 3).
BUTTON_MODE_PIN = 13
BUTTON_UP_PIN = 14
BUTTON_DOWN_PIN = 15

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
    """The three buttons, in the order (mode, up, down)."""
    return (Pin(BUTTON_MODE_PIN, Pin.IN, Pin.PULL_UP),
            Pin(BUTTON_UP_PIN, Pin.IN, Pin.PULL_UP),
            Pin(BUTTON_DOWN_PIN, Pin.IN, Pin.PULL_UP))


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
