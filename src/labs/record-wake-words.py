"""Record the wake phrase to WAV files on the Pico, one take per button press.

This is a measurement tool, not a lab. It exists because Lab 4 kept asking
questions that cannot be answered from the board's console -- how long is the
phrase really, where does its energy sit, how far above the room noise does it
actually rise -- and the honest way to answer them is to capture the audio once
and analyze it properly on a computer, instead of guessing at a threshold and
re-running the detector to see what happens.

Each take is written to a separate file:

    sounds/hey-pico-01.wav ... sounds/hey-pico-10.wav

Fetch them afterwards into docs/sounds/, which is where the Wake Word Explorer
dashboard serves them from:

    mpremote connect <port> fs cp :sounds/*.wav docs/sounds/

and delete them from the board when you are done -- ten takes is about 768 KB,
and the Pico 2's filesystem only has ~3 MB in it. Note that `fs rm -r` does NOT
work here: mpremote 1.24.1 fails with OSError 39 (ENOTEMPTY) on a directory
that still has files in it, so the delete has to be spelled out:

    mpremote connect <port> exec "import os; d='sounds'; [os.remove(d+'/'+f) for f in os.listdir(d)]; os.rmdir(d)"

Run it the same way as the labs:

    mpremote connect <port> run src/labs/record-wake-words.py

BUTTONS:  SELECT starts a take, and advances to the next one afterwards.
          MODE   re-records the take you just did, if you flubbed it.
"""

import os
import struct
import time

import config

# ---------------------------------------------------------------------------
# Parameters -- these are the knobs worth turning.
# ---------------------------------------------------------------------------

WAKE_WORD_COUNT = 10        # how many takes to record
RECORD_SECONDS = 3.0        # length of each take
PHRASE_SLUG = "hey-pico"    # file name stem: hey-pico-01.wav, -02, ...
SOUNDS_DIR = "sounds"       # directory on the Pico's flash

# How much to amplify on the way from the microphone's 24 bits to the file's
# 16, expressed as a left shift: 0 is a straight conversion, 2 multiplies by 4.
#
# This needs a number because the INMP441 leaves most of its range unused. The
# loudest sample Lab 3 ever measured in this room was 816,803 out of a possible
# 8,388,608 -- 9.7% of full scale, or 20 dB of headroom nobody is using. A
# straight 24-to-16 bit conversion would carry that waste into the file and
# leave speech peaking at a tenth of the WAV's range.
#
# 2 is deliberately conservative rather than optimal. It puts that same 816,803
# peak at 39% of full scale, which leaves 8 dB in hand for a take spoken louder
# or closer than the one that was measured. 3 would look better on a meter and
# leaves only 2 dB, which is not enough margin to bet a recording session on --
# clipping cannot be undone afterwards, and quiet can. Every take reports its
# peak, so if yours are consistently landing under 20% raise this to 3 and
# re-record.
GAIN_SHIFT = 2

# ---------------------------------------------------------------------------
# Derived constants
# ---------------------------------------------------------------------------

PROGRAM = "record-wake-words"
VERSION = "1.0.0"

FRAME_SAMPLES = 256                     # matches the labs, so timing is familiar
FRAME_FMT = "<%di" % FRAME_SAMPLES
RATE = config.SAMPLE_RATE

# Round the recording up to a whole number of frames -- readinto() delivers a
# frame at a time, and a partial one at the end would just be silence anyway.
FRAMES = int((RECORD_SECONDS * RATE + FRAME_SAMPLES - 1) // FRAME_SAMPLES)
TOTAL_SAMPLES = FRAMES * FRAME_SAMPLES
ACTUAL_SECONDS = TOTAL_SAMPLES / RATE

# The microphone hands over 32-bit words with 24 bits of audio at the top, so
# `w >> 8` is the 24-bit sample and `w >> 16` is that sample as 16-bit. The
# gain is applied by shifting less than the full 16.
SAMPLE_SHIFT = 16 - GAIN_SHIFT

BITS = 16
CHANNELS = 1

# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------

oled = config.init_display()
button_mode, button_select = config.init_buttons()
took, poll_buttons = config.latch_buttons(button_mode, button_select)
led = config.init_led()

# Both buffers are allocated ONCE, here, while the heap is still clean.
#
# This is not tidiness. Lab 4 learned the hard way that allocating a large
# block after a long run of small ones fails with MemoryError while hundreds of
# kilobytes are still free, because what is left is fragmented into pieces too
# small to use. `pcm` is 76,800 bytes for a 3 second take -- easily the biggest
# thing this program asks for, and the last thing that should be requested late.
raw = bytearray(FRAME_SAMPLES * 4)
pcm = bytearray(TOTAL_SAMPLES * 2)

mic = None                              # opened below, after the flash work


def wav_header(data_bytes):
    """The 44-byte RIFF/WAVE header for our fixed format.

    Written per file rather than kept as a constant because the size fields
    depend on the payload, and a WAV whose header disagrees with its data is
    the kind of file that opens fine in one tool and not in another.
    """
    byte_rate = RATE * CHANNELS * BITS // 8
    block_align = CHANNELS * BITS // 8
    return (b"RIFF" + struct.pack("<I", 36 + data_bytes) + b"WAVE" +
            b"fmt " + struct.pack("<IHHIIHH", 16, 1, CHANNELS, RATE,
                                  byte_rate, block_align, BITS) +
            b"data" + struct.pack("<I", data_bytes))


def take_path(n):
    return "%s/%s-%02d.wav" % (SOUNDS_DIR, PHRASE_SLUG, n)


def prepare_dir():
    """Create the sounds directory and report what is already in it.

    Runs BEFORE the microphone is opened, because it touches the filesystem --
    see the note in save_take() for why that ordering is not optional.

    Existing takes are kept, not overwritten. A session that ends early (a
    pulled cable, a Ctrl-C, a hard fault) should cost you the take you were on,
    not the nine before it.
    """
    try:
        os.mkdir(SOUNDS_DIR)
    except OSError:
        pass                            # already there

    done = []
    for n in range(1, WAKE_WORD_COUNT + 1):
        try:
            os.stat(take_path(n))
            done.append(n)
        except OSError:
            pass
    return done


def drain_mic():
    """Throw away whatever accumulated in the mic's buffer while we waited.

    config.MIC_BUFFER_BYTES is 40,000 -- 781 ms of audio -- and nothing has
    read the microphone during the countdown, so it is full of the room, the
    button click, and possibly the tail of the last take. Recording without
    this puts all of that at the front of the file.
    """
    for _ in range(config.MIC_BUFFER_BYTES // len(raw) + 4):
        mic.readinto(raw)


def capture():
    """Fill `pcm` with one take. Returns (peak24, clipped, elapsed_ms).

    The peak is reported in 24-bit units so it can be compared directly against
    the numbers in calibration.json, which are in those units too.
    """
    drain_mic()

    out = 0
    peak_word = 0
    clipped = 0
    t0 = time.ticks_ms()

    for _ in range(FRAMES):
        mic.readinto(raw)
        words = struct.unpack(FRAME_FMT, raw)
        for w in words:
            a = w if w >= 0 else -w
            if a > peak_word:
                peak_word = a

            s = w >> SAMPLE_SHIFT
            if s > 32767:
                s = 32767
                clipped += 1
            elif s < -32768:
                s = -32768
                clipped += 1

            # Little-endian signed 16-bit, written by hand. struct.pack_into
            # would be tidier and measurably slower, and this loop runs 38,400
            # times per take inside a real-time deadline.
            pcm[out] = s & 0xFF
            pcm[out + 1] = (s >> 8) & 0xFF
            out += 2

    return peak_word >> 8, clipped, time.ticks_diff(time.ticks_ms(), t0)


def measure_rms():
    """RMS of the take just captured, in 24-bit units.

    A second pass rather than part of the capture loop, on purpose: this runs
    after the microphone has stopped, where being slow costs nothing. Doing it
    inline would put a multiply and a growing accumulator inside the one loop
    in this program that has a deadline.

    No DC removal. The offset was measured on this hardware at -1,087 in 24-bit
    units -- 0.013% of full scale, and 2.3% of the room's noise ENERGY, which
    is 0.1 dB. It is also below the 150 Hz where the detector's bands start, so
    it never reaches the analysis at all. Worth checking, not worth correcting.
    """
    acc = 0
    for i in range(0, len(pcm), 2):
        v = pcm[i] | (pcm[i + 1] << 8)
        if v >= 32768:
            v -= 65536
        acc += v * v
    rms16 = (acc / TOTAL_SAMPLES) ** 0.5
    # Back to 24-bit units. The file holds `w >> (16 - GAIN_SHIFT)` while a
    # 24-bit sample is `w >> 8`, so the stored value sits 8 - GAIN_SHIFT bits
    # low -- a factor of 64 at the default, not the 4 that GAIN_SHIFT alone
    # suggests. Getting this wrong does not make the number look wrong: it
    # stays perfectly self-consistent and is quietly 24 dB out, which is
    # exactly how it survived a full session of being read off and reasoned
    # about. The peak reported alongside it comes from `peak_word >> 8` and
    # was right all along, which is what caught it.
    return rms16 * (1 << (8 - GAIN_SHIFT))


def save_take(n):
    """Write `pcm` to the take's WAV file. Returns True on success.

    THE MICROPHONE IS CLOSED FIRST, AND THIS IS NOT OPTIONAL.

    Writing flash while an I2S stream is open hard-faults the RP2350. Not an
    exception -- the board stops dead, mid-write, and stays dead through a soft
    reset until the USB cable is pulled. There is no traceback to find it by.
    Lab 3 lost an afternoon to this, and a program whose whole purpose is to
    alternate between recording and writing files is exactly where it would
    happen again.
    """
    global mic

    mic.deinit()

    path = take_path(n)
    tmp = path + ".tmp"
    ok = False
    try:
        # Written to a temp name and renamed into place. open(path, "w")
        # truncates immediately, so an interruption partway through would
        # leave a half-written WAV sitting where a good take used to be.
        with open(tmp, "wb") as f:
            f.write(wav_header(len(pcm)))
            f.write(pcm)
        try:
            os.remove(path)
        except OSError:
            pass                        # first write: nothing to replace
        os.rename(tmp, path)
        ok = True
    except OSError as e:
        print("WARNING: could not write %s (%s)" % (path, e))
        try:
            os.remove(tmp)
        except OSError:
            pass
    finally:
        # Always reopen, even if the write failed. Every later take needs it.
        mic = config.init_microphone()
    return ok


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

def screen(title, l1="", l2="", l3=""):
    oled.fill(config.BLACK)
    oled.text(title, 0, 2, config.WHITE)
    oled.text(l1, 0, 20, config.WHITE)
    oled.text(l2, 0, 32, config.WHITE)
    oled.text(l3, 0, 48, config.WHITE)
    oled.show()


def wait_for(*names):
    """Block until one of `names` is pressed; return which one."""
    while True:
        for name in names:
            if took(name):
                return name
        time.sleep_ms(20)


def countdown():
    for c in (3, 2, 1):
        screen("GET READY", "say the phrase", "when it says", "SPEAK  ...%d" % c)
        for _ in range(10):             # 10 x 100 ms, buttons stay responsive
            poll_buttons()
            time.sleep_ms(100)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("Recording %d takes of \"%s\", %.2f s each" %
      (WAKE_WORD_COUNT, PHRASE_SLUG, ACTUAL_SECONDS))
print("%d Hz, %d-bit mono, gain x%d -> %s/%s-NN.wav (%d bytes each)" %
      (RATE, BITS, 1 << GAIN_SHIFT, SOUNDS_DIR, PHRASE_SLUG, len(pcm) + 44))
print()
print("BUTTONS:  SELECT starts a take, and advances afterwards")
print("          MODE   re-records the take you just did")
print()

already = prepare_dir()
if already:
    print("already recorded: %s" % ", ".join("%02d" % n for n in already))
    print("(to start over, delete them -- see the note at the top of this file)")
    print()

mic = config.init_microphone()

try:
    take = 1
    while take <= WAKE_WORD_COUNT:
        if take in already:
            take += 1
            continue

        screen("TAKE %d of %d" % (take, WAKE_WORD_COUNT),
               "press SELECT", "to record", "%.1f seconds" % ACTUAL_SECONDS)
        wait_for("select")

        countdown()

        screen("SPEAK NOW", "", "  \"%s\"" % PHRASE_SLUG.replace("-", " "))
        led.on()
        peak, clipped, elapsed = capture()
        led.off()

        rms = measure_rms()
        pct = 100.0 * peak / config.FULL_SCALE
        ok = save_take(take)

        # The overrun check. readinto() blocks for exactly as long as the audio
        # takes, so a take that finishes late means the conversion loop could
        # not keep up and the microphone's buffer absorbed the difference. A
        # little is harmless; a lot means samples were eventually dropped.
        late = elapsed - int(ACTUAL_SECONDS * 1000)

        print("take %02d  peak %7d (%.1f%% FS)  rms %7.0f  %s" %
              (take, peak, pct, rms, "saved" if ok else "NOT SAVED"))
        if clipped:
            print("   -> %d samples CLIPPED; lower GAIN_SHIFT and re-record" % clipped)
        if pct < 5.0:
            print("   -> very quiet; move closer or speak up")
        if late > 100:
            print("   -> capture ran %d ms late; samples may have been dropped" % late)

        screen("TAKE %d saved" % take if ok else "TAKE %d FAILED" % take,
               "peak %.1f%%" % pct,
               "clip %d" % clipped if clipped else "",
               "SELECT=next MODE=redo")

        if wait_for("select", "mode") == "mode":
            print("   -> re-recording take %02d" % take)
            continue                    # same index, record it again

        take += 1

    screen("ALL DONE", "%d takes" % WAKE_WORD_COUNT, "in %s/" % SOUNDS_DIR, "Ctrl-C to exit")
    print()
    print("Done. Fetch them with:")
    print("    mpremote connect <port> fs cp -r :%s ." % SOUNDS_DIR)
    while True:
        time.sleep_ms(200)

except KeyboardInterrupt:
    if mic is not None:
        mic.deinit()
    led.off()
    screen("Stopped.", "", "", "")
    print()
    print("Stopped.")
