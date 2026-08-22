"""Hey Pico: a wake word, a spoken command, and a countdown timer.

This is the first program in the course where the whole loop closes. Lab 4
proved the detector fires on "Hey Pico"; this one acts on what comes after it.

    "Hey Pico, set a timer for five minutes"
     ^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
     matched   recorded and sent to the host, which
     on-chip   recognizes the words and replies with seconds

The split is the whole point, and it is the same split every commercial smart
speaker makes. Recognizing ONE fixed phrase is cheap enough to run forever on a
$7 microcontroller with no network at all. Recognizing ARBITRARY speech is not,
and will not be. The wake word is what buys the right to spend the expensive
resource. Here "the cloud" is a laptop on the other end of the USB cable --
the same architecture, with the latency and the privacy cost made visible.

RUN IT FROM THE HOST, not with mpremote:

    python3 src/tools/hey-pico-server.py

The server owns the serial port, starts this program on the board, receives the
audio, and answers. Under `mpremote run` this works right up to the moment it
asks the host a question and nothing replies.

FIRST RUN enrolls the wake word -- ENROLL_TAKES repetitions, saved to flash, so
it happens once. Delete hey-pico-template.json from the Pico to redo it.
"""

import binascii
import gc
import json
import math
import os
import struct
import sys
import time

import config
import fft_asm

# --- These MUST match Lab 4 ------------------------------------------------
# A template enrolled under one set of bands is meaningless under another: it
# is a vector in a space that no longer exists. If Lab 4 moves, this moves.
N = 256
BANDS = 12
BAND_LO_HZ = 350
BAND_HI_HZ = 6000
TEMPLATE_FRAMES = 32
THRESHOLD = 0.70
SPEECH_FLOOR = config.SPEECH_FLOOR      # band-limited since config v2.4.0
REFRACTORY_MS = 1500

# --- Tool parameters -------------------------------------------------------
COMMAND_SECONDS = 3.0                   # recording window AFTER the wake word
ENROLL_TAKES = 4
TEMPLATE_FILE = "hey-pico-template.json"

PROGRAM = "hey-pico-timer"
VERSION = "1.0.0"

# The framing the host looks for. Distinctive on purpose: this shares a serial
# line with MicroPython's own REPL chatter and any stray print() in the code.
HDR = "<<<AUDIO"
FTR = "<<<END>>>"
B64_CHUNK = 480                         # divisible by 3, so no padding mid-stream

# --- Memory ----------------------------------------------------------------
# The command buffer is claimed FIRST, before any peripheral, because it is by
# far the largest single thing this program needs -- 76,800 bytes for a three
# second recording -- and the last thing that should be asked for late.
#
# If this raises MemoryError, the board is almost certainly carrying state from
# a program run before it. The raw REPL does not restart the interpreter, so
# earlier globals survive and gc.collect() cannot reclaim them; a soft reset
# (Ctrl-D at the REPL) recovers around 200 KB. hey-pico-server.py does that
# automatically before it starts this file.
gc.collect()
COMMAND_FRAMES = int(COMMAND_SECONDS * config.SAMPLE_RATE) // N
COMMAND_SAMPLES = COMMAND_FRAMES * N
pcm = bytearray(COMMAND_SAMPLES * 2)

# --- Hardware --------------------------------------------------------------
# The rest, still early, still while the heap is clean. Lab 4 learned this the
# expensive way when a 20 KB speaker buffer failed to allocate with 475 KB
# free but none of it contiguous.
oled = config.init_display()
button_mode, button_select = config.init_buttons()
took, poll_buttons = config.latch_buttons(button_mode, button_select)
led = config.init_led()
mic = config.init_microphone()
speaker = config.init_speaker()
amp = config.init_amp_enable()

fft = fft_asm.FFT(N)
re, im = fft.make_buffers()
raw = bytearray(N * 4)

beep_wake = config.tone_buffer(1320, 90)
beep_done = config.tone_buffer(880, 400)

window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]
BAND_RMS_SCALE = 2.0 / (N * N * (sum(w * w for w in window) / N))

bin_hz = config.SAMPLE_RATE / N
lo_bin = max(1, int(BAND_LO_HZ / bin_hz))
hi_bin = min(N // 2 - 1, int(BAND_HI_HZ / bin_hz))
ratio = (hi_bin / lo_bin) ** (1.0 / BANDS)
edges = [int(lo_bin * (ratio ** b)) for b in range(BANDS + 1)]
for b in range(BANDS):
    if edges[b + 1] <= edges[b]:
        edges[b + 1] = edges[b] + 1

ring = [[0.0] * BANDS for _ in range(TEMPLATE_FRAMES)]
ring_rms = [0.0] * TEMPLATE_FRAMES
ring_pos = 0
frames_seen = 0
template = None


def screen(l1, l2="", l3="", big=False):
    oled.fill(config.BLACK)
    if big:
        oled.text(l1, 0, 12, config.WHITE)
        oled.text(l2, 0, 30, config.WHITE)
        oled.text(l3, 0, 48, config.WHITE)
    else:
        oled.text(l1, 0, 2, config.WHITE)
        oled.hline(0, 12, config.WIDTH, config.WHITE)
        oled.text(l2, 0, 24, config.WHITE)
        oled.text(l3, 0, 40, config.WHITE)
    oled.show()


def feature_frame():
    """One frame: (unit band vector, band-limited RMS). Identical to Lab 4."""
    n = mic.readinto(raw)
    count = n // 4
    words = struct.unpack("<%di" % count, raw[:count * 4])

    total = 0
    for w in words:
        total += w >> 8
    dc = total / count

    for i in range(N):
        s = ((words[i] >> 8) - dc) if i < count else 0.0
        re[i] = s * window[i]
        im[i] = 0.0

    fft.run(re, im)

    band_total = 0.0
    vec = [0.0] * BANDS
    for b in range(BANDS):
        acc = 0.0
        for k in range(edges[b], edges[b + 1]):
            acc += re[k] * re[k] + im[k] * im[k]
        band_total += acc
        vec[b] = math.log(1.0 + acc / (edges[b + 1] - edges[b]))

    mean = 0.0
    for b in range(BANDS):
        mean += vec[b]
    mean /= BANDS
    for b in range(BANDS):
        vec[b] -= mean

    norm = 0.0
    for b in range(BANDS):
        norm += vec[b] * vec[b]
    norm = math.sqrt(norm)
    if norm > 0:
        for b in range(BANDS):
            vec[b] /= norm
    return vec, math.sqrt(BAND_RMS_SCALE * band_total)


def push(vec, rms):
    global ring_pos, frames_seen
    ring[ring_pos] = vec
    ring_rms[ring_pos] = rms
    ring_pos = (ring_pos + 1) % TEMPLATE_FRAMES
    if frames_seen < TEMPLATE_FRAMES * 2:
        frames_seen += 1


def window_score():
    if template is None or frames_seen < TEMPLATE_FRAMES:
        return 0.0
    total = 0.0
    for f in range(TEMPLATE_FRAMES):
        live = ring[(ring_pos + f) % TEMPLATE_FRAMES]
        ref = template[f]
        acc = 0.0
        for b in range(BANDS):
            acc += live[b] * ref[b]
        total += acc
    return total / TEMPLATE_FRAMES


def drain_mic():
    for _ in range(config.MIC_BUFFER_BYTES // len(raw) + 4):
        mic.readinto(raw)


# ---------------------------------------------------------------------------
# Enrollment and the saved template
# ---------------------------------------------------------------------------

def save_template(tpl):
    """Write the template to flash. THE MICROPHONE IS CLOSED FIRST.

    Writing flash with an I2S stream open hard-faults the RP2350 -- no
    exception, no traceback, dead until the USB cable is pulled. Lab 3 lost an
    afternoon to it. Anything in this file that touches the filesystem does the
    same deinit/reinit dance, and nothing may be added that does not.
    """
    global mic
    mic.deinit()
    ok = False
    tmp = TEMPLATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"bands": BANDS, "frames": TEMPLATE_FRAMES,
                       "band_lo_hz": BAND_LO_HZ, "band_hi_hz": BAND_HI_HZ,
                       "template": tpl}, f)
        try:
            os.remove(TEMPLATE_FILE)
        except OSError:
            pass
        os.rename(tmp, TEMPLATE_FILE)
        ok = True
    except (OSError, MemoryError) as e:
        print("WARNING: could not save template (%s)" % e)
        try:
            os.remove(tmp)
        except OSError:
            pass
    finally:
        mic = config.init_microphone()
    return ok


def load_template():
    """Return the saved template, or None if there is nothing usable.

    The band settings are checked, not assumed. A template recorded before
    BAND_LO_HZ moved from 150 to 350 Hz would load without complaint and match
    nothing, which is a far worse failure than refusing it outright.
    """
    try:
        with open(TEMPLATE_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if (d.get("bands") != BANDS or d.get("frames") != TEMPLATE_FRAMES or
            d.get("band_lo_hz") != BAND_LO_HZ or d.get("band_hi_hz") != BAND_HI_HZ):
        print("saved template was made with different bands -- re-enrolling")
        return None
    return d.get("template")


def enroll():
    """Record ENROLL_TAKES repetitions and average them into a template."""
    global template
    acc = [[0.0] * BANDS for _ in range(TEMPLATE_FRAMES)]

    print("Enrolling the wake word. Say 'Hey Pico' %d times." % ENROLL_TAKES)
    for take in range(1, ENROLL_TAKES + 1):
        screen("ENROLL %d/%d" % (take, ENROLL_TAKES),
               "press SELECT", "then say it")
        while not took("select"):
            time.sleep_ms(20)
        for c in (3, 2, 1):
            screen("ENROLL %d/%d" % (take, ENROLL_TAKES), "get ready", "%d" % c)
            time.sleep_ms(700)
        screen("SAY IT NOW", "", "  Hey Pico", big=True)
        drain_mic()
        peak = 0.0
        for f in range(TEMPLATE_FRAMES):
            vec, rms = feature_frame()
            if rms > peak:
                peak = rms
            for b in range(BANDS):
                acc[f][b] += vec[b]
        print("  take %d recorded, peak %.0f%s"
              % (take, peak, "  (quiet -- speak up)" if peak < SPEECH_FLOOR else ""))
        screen("recorded %d/%d" % (take, ENROLL_TAKES), "peak %.0f" % peak, "")
        time.sleep_ms(800)

    built = []
    for f in range(TEMPLATE_FRAMES):
        vec = [acc[f][b] / ENROLL_TAKES for b in range(BANDS)]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        built.append(vec)
    template = built
    if save_template(built):
        print("template saved to %s" % TEMPLATE_FILE)


# ---------------------------------------------------------------------------
# Talking to the host
# ---------------------------------------------------------------------------

def record_command():
    """Fill `pcm` with COMMAND_SECONDS of audio, starting now.

    No drain first, deliberately. The wake word has only just finished and the
    command follows it without a pause -- "Hey Pico, set a timer" is one breath,
    not two. Throwing away the buffered audio here would clip the first word
    off every command.
    """
    out = 0
    for _ in range(COMMAND_FRAMES):
        n = mic.readinto(raw)
        count = n // 4
        words = struct.unpack("<%di" % count, raw[:count * 4])
        for i in range(N):
            s = (words[i] >> 14) if i < count else 0
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            pcm[out] = s & 0xFF
            pcm[out + 1] = (s >> 8) & 0xFF
            out += 2


def send_command_audio():
    """Stream `pcm` to the host as base64 between the frame markers.

    Base64 rather than raw bytes because this shares one USB CDC line with the
    REPL, and a raw 0x04 in the middle of a PCM sample means end-of-output to
    everything upstream. Text costs 33% more and removes a whole class of
    corruption that only shows up on some recordings.
    """
    print("%s rate=%d bits=16 samples=%d>>>"
          % (HDR, config.SAMPLE_RATE, COMMAND_SAMPLES))
    for i in range(0, len(pcm), B64_CHUNK):
        sys.stdout.write(binascii.b2a_base64(pcm[i:i + B64_CHUNK]).decode())
    print(FTR)


def ask_host():
    """Send the audio, then block until the host answers with one line.

    Replies are:
        TIMER <seconds> <text to show>
        SORRY <text to show>
    """
    send_command_audio()
    line = sys.stdin.readline()
    if not line:
        return None, "no reply from host"
    # Split the verb off first, then the rest. Splitting into three at once
    # works for TIMER but truncates SORRY to its first word, which is how
    # "not understood" reached the display as just "not".
    head = line.strip().split(None, 1)
    if not head:
        return None, "empty reply"
    verb = head[0]
    rest = head[1] if len(head) > 1 else ""
    if verb == "TIMER":
        bits = rest.split(None, 1)
        try:
            return int(bits[0]), (bits[1] if len(bits) > 1 else "timer running")
        except (ValueError, IndexError):
            return None, "bad reply"
    return None, rest or "not understood"


# ---------------------------------------------------------------------------
# The timer
# ---------------------------------------------------------------------------

def mmss(seconds):
    return "%d:%02d" % (seconds // 60, seconds % 60)


def run_timer(seconds, text):
    """Count down, redrawing once a second. SELECT cancels.

    The microphone is left open and unread throughout. Its buffer fills within
    the first second and stays full, which is harmless -- the detector is not
    running, and every read after the timer drains it before listening resumes.
    """
    print("%s (%s)" % (text, mmss(seconds)))
    end = time.ticks_add(time.ticks_ms(), seconds * 1000)
    last = -1
    while True:
        remaining = time.ticks_diff(end, time.ticks_ms())
        if remaining <= 0:
            break
        if took("select"):
            screen("CANCELLED", "", "")
            print("timer cancelled")
            time.sleep_ms(1200)
            return
        secs = (remaining + 999) // 1000
        if secs != last:
            last = secs
            screen("TIMER", mmss(secs), "SELECT cancels")
        time.sleep_ms(50)

    print("TIME'S UP")
    for _ in range(3):
        screen("TIME'S UP!", "", "", big=True)
        speaker.write(beep_done)
        oled.fill(config.BLACK)
        oled.show()
        time.sleep_ms(250)
    screen("TIME'S UP!", "", "press SELECT", big=True)
    while not took("select"):
        time.sleep_ms(20)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("wake word gate %.0f, threshold %.2f, command window %.1f s"
      % (SPEECH_FLOOR, THRESHOLD, COMMAND_SECONDS))

template = load_template()
if template is None:
    enroll()
else:
    print("loaded wake word template from %s" % TEMPLATE_FILE)

last_detect = time.ticks_add(time.ticks_ms(), -REFRACTORY_MS)

try:
    while True:
        screen("Hey Pico", "listening...", "")
        drain_mic()
        frames_seen = 0

        # --- listen ---------------------------------------------------------
        while True:
            poll_buttons()
            vec, rms = feature_frame()
            push(vec, rms)

            now = time.ticks_ms()
            if (frames_seen >= TEMPLATE_FRAMES and
                    time.ticks_diff(now, last_detect) > REFRACTORY_MS and
                    max(ring_rms) > SPEECH_FLOOR and
                    window_score() >= THRESHOLD):
                last_detect = now
                break

        # --- wake ------------------------------------------------------------
        led.on()
        print("WAKE  score=%.3f  rms=%.0f" % (window_score(), max(ring_rms)))
        screen("Yes?", "listening for", "your command")
        speaker.write(beep_wake)

        # --- command ---------------------------------------------------------
        record_command()
        led.off()
        screen("thinking...", "", "")
        seconds, text = ask_host()

        if seconds is None:
            print("host: %s" % text)
            screen("Sorry --", text[:16], "try again")
            time.sleep_ms(2500)
        else:
            screen("OK", text[:16], mmss(seconds))
            time.sleep_ms(1200)
            run_timer(seconds, text)

except KeyboardInterrupt:
    mic.deinit()
    speaker.deinit()
    led.off()
    screen("Stopped.", "", "")
    print()
    print("Stopped.")
