# Lab 3: Microphone Calibration -- find the numbers Lab 4 depends on.
#
# Lab 4's detector needs one measured constant: SPEECH_FLOOR, the loudness gate
# that separates "someone is talking" from "the room is just sitting there".
# That gate is not optional. The feature vectors are loudness-normalized, so
# normalized room noise correlates with normalized room noise perfectly well --
# without a gate, silence scores against the template all day.
#
# Guessing that constant goes wrong in both directions, and both look like bugs
# somewhere else:
#   too HIGH -> "the detector cannot hear me"      (really: gated out)
#   too LOW  -> "it fires at nothing"              (really: noise scored)
#
# So measure it. Six modes; MODE advances, SELECT acts on the current one:
#
#   0 NOISE    the room with nobody talking
#   1 SPEECH   you, at the distance you will actually use
#   2 CLIP     headroom check -- are you overloading the microphone?
#   3 SPECTRUM which bands the room's noise actually occupies
#   4 RESULT   the SPEECH_FLOOR to paste into config.py
#   5 CLEAR    throw it all away and start over
#
# CLEAR is a mode rather than a second button because the kit has only two
# buttons, and because a destructive action you have to walk the whole mode
# list to reach cannot fire from a stray press.
#
# Nothing here is real-time critical, so unlike Lab 4 this lab draws freely.

import gc
import json
import math
import os
import struct
import time

import config

try:
    import fft_asm as fftmod
    ASM = True
except (ImportError, SyntaxError):
    import fftlab as fftmod
    ASM = False

N = 256
FRAME_MS = N / config.SAMPLE_RATE * 1000

MEASURE_MS = 5000                        # how long each measurement runs
FRAMES = int(MEASURE_MS / FRAME_MS)

PROGRAM = "03-mic-calibration"
# 1.7.0: close the mic across the flash write. The I2S DMA interrupt firing
# during a flash program hard-faulted the chip, which looked like a dead MODE
# button. 1.6.0: buttons latched by IRQ *and* polling, polled during measurements.
# 1.5.0: buttons latched by IRQ. 1.4.0: two buttons + CLEAR mode, crash-safe JSON write, full mic-buffer
# drain before each measurement, per-measurement timing and short-read detection.
VERSION = "1.7.0"

RESULTS_FILE = "calibration.json"        # written to the Pico's own flash

# EDIT THIS LINE before you measure. A noise floor without its room is not a
# result, and by the time this JSON reaches a laptop nobody remembers which
# room it came from or how far away you were sitting.
ROOM_NOTE = "The room is my shop in the basement and there is a furnace fan running. I sit 15 inches from the Mic above the display over the Pico 2."

BANDS = 12                               # must match Lab 4
BAND_LO_HZ = 150
BAND_HI_HZ = 6000

MODES = ["NOISE", "SPEECH", "CLIP", "SPECTRUM", "RESULT", "CLEAR"]
(MODE_NOISE, MODE_SPEECH, MODE_CLIP, MODE_SPECTRUM,
 MODE_RESULT, MODE_CLEAR) = range(6)

# Reprinted every time MODE advances, so the console always says what the
# button you are about to press is going to do. One tuple of lines per mode.
MODE_HELP = (
    ("Leave the room exactly as you will use it. Stay silent, press SELECT.",),
    ("Press SELECT, then say 'Hey Pico' over and over -- at the distance you",
     "will really use -- until the progress bar fills.",
     "REQUIRED: without this there is nothing to recommend."),
    ("Press SELECT, then speak as LOUDLY as you ever would.",
     "Headroom check only; this does not feed the recommendation."),
    ("Stay silent again and press SELECT.",
     "Shows which frequency bands the room's noise actually occupies."),
    ("Press SELECT to reprint the summary and rewrite " + RESULTS_FILE + ".",),
    ("Press SELECT to throw away every measurement and start over.",
     "Nothing is cleared until you press it."),
)


def announce(m):
    """Print the current mode and what to do in it."""
    print()
    print(">>> Mode %d/%d: %s" % (m + 1, len(MODES), MODES[m]))
    for line in MODE_HELP[m]:
        print("    " + line)

oled = config.init_display()
button_mode, button_select = config.init_buttons()
mic = config.init_microphone()
raw = bytearray(N * 4)

fft = fftmod.FFT(N)
try:
    re, im = fft.make_buffers()
except AttributeError:
    re, im = fft.buffers()

window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]

bin_hz = config.SAMPLE_RATE / N
lo_bin = max(1, int(BAND_LO_HZ / bin_hz))
hi_bin = min(N // 2 - 1, int(BAND_HI_HZ / bin_hz))
ratio = (hi_bin / lo_bin) ** (1.0 / BANDS)
edges = [int(lo_bin * (ratio ** b)) for b in range(BANDS + 1)]
for b in range(BANDS):
    if edges[b + 1] <= edges[b]:
        edges[b + 1] = edges[b] + 1

# Results, filled in as each measurement completes. None means "not yet run".
noise_rms = None        # median frame RMS with the room quiet
noise_max = None        # loudest frame seen while "quiet" -- the real enemy
noise_pct = None        # full frame-RMS distribution of the quiet room
speech_rms = None       # median frame RMS while talking
speech_peak = None      # loudest frame while talking
speech_pct = None       # full frame-RMS distribution while talking
clip_peak = None        # largest raw sample magnitude
noise_bands = None      # per-band noise energy
collect_stats = None    # timing/short-read stats from the last measurement

mode = MODE_NOISE

# Presses are latched by interrupt rather than polled: a measurement blocks
# this program for about eight seconds, and a press that starts and ends inside
# that window would never be seen at all. See config.latch_buttons().
took, poll_buttons = config.latch_buttons(button_mode, button_select)


def frame_rms():
    """One frame: return (rms of the AC part, peak sample, samples read).

    The sample count is returned because readinto() is allowed to come back
    short. A short read is not an error, but it means the frame covers less
    time than FRAME_MS claims -- and if it happens on every frame, a
    measurement that says "5 seconds" is really listening for far less.
    """
    n = mic.readinto(raw)
    count = n // 4
    words = struct.unpack("<%di" % count, raw[:count * 4])
    total = 0
    for w in words:
        total += w >> 8
    dc = total / count
    energy = 0.0
    peak = 0
    for w in words:
        s = (w >> 8) - dc
        energy += s * s
        a = s if s >= 0 else -s
        if a > peak:
            peak = a
    return math.sqrt(energy / count), peak, count


def collect(label, seconds_note):
    """Run one measurement for MEASURE_MS, returning sorted frame RMS values.

    Returns (sorted_rms_list, peak_sample). A progress bar is drawn between
    frames -- the mic keeps buffering during the redraw, and since this lab is
    not doing continuous detection a few dropped frames cost nothing.
    """
    global collect_stats
    values = []
    peak_sample = 0
    lo_count = hi_count = None
    t_start = time.ticks_ms()
    for f in range(FRAMES):
        poll_buttons()          # a press made mid-measurement must not be lost
        r, p, c = frame_rms()
        values.append(r)
        if lo_count is None or c < lo_count:
            lo_count = c
        if hi_count is None or c > hi_count:
            hi_count = c
        if p > peak_sample:
            peak_sample = p
        if f % 8 == 0:
            oled.fill(config.BLACK)
            oled.text("Lab 3: " + label, 0, 0, config.WHITE)
            oled.hline(0, 10, config.WIDTH, config.WHITE)
            oled.text(seconds_note, 0, 18, config.WHITE)
            oled.text("%.0f dBFS" % config.dbfs(r), 0, 32, config.WHITE)
            oled.rect(0, 46, config.WIDTH, 10, config.WHITE)
            filled = int((f + 1) / FRAMES * (config.WIDTH - 4))
            if filled > 0:
                oled.fill_rect(2, 48, filled, 6, config.WHITE)
            oled.show()
    elapsed = time.ticks_diff(time.ticks_ms(), t_start)
    collect_stats = {
        "frames": FRAMES,
        "elapsed_ms": elapsed,
        "expected_ms": MEASURE_MS,
        "samples_per_frame_min": lo_count,
        "samples_per_frame_max": hi_count,
        "samples_per_frame_expected": N,
    }
    # A measurement that runs far short of its wall-clock budget did not listen
    # for as long as it claims, and every level in it is drawn from less audio
    # than intended. Worth shouting about rather than burying in the JSON.
    if elapsed < MEASURE_MS * 0.8:
        print("  !! took only %d ms of the expected %d ms" % (elapsed, MEASURE_MS))
        print("     samples/frame ran %d..%d, expected %d"
              % (lo_count, hi_count, N))
        print("     readinto() is returning short -- this measurement covers")
        print("     less audio than it claims. Do not trust it.")
    values.sort()
    return values, peak_sample


def median(sorted_values):
    return sorted_values[len(sorted_values) // 2]


def percentiles(sorted_values):
    """The whole frame-RMS distribution, not just the median and the max.

    The gap between p50 and p99 is what decides whether a workable gate exists
    at all. A room whose loudest "quiet" frames sit 9 dB above its median needs
    a far higher SPEECH_FLOOR than the median alone would suggest, and a single
    max value cannot tell you whether that was one door slam or a steady rattle
    in every eighth frame.
    """
    n = len(sorted_values)
    out = {}
    for p in (10, 25, 50, 75, 90, 99):
        out["p%d" % p] = sorted_values[min(n - 1, int(n * p / 100))]
    out["max"] = sorted_values[-1]
    out["frames"] = n
    return out


def measure_noise():
    global noise_rms, noise_max, noise_pct
    countdown("Be QUIET", "measuring room")
    vals, _ = collect("NOISE", "stay quiet...")
    noise_rms = median(vals)
    noise_max = vals[-1]
    noise_pct = percentiles(vals)
    print("noise floor : median %8.0f  (%.1f dBFS, ~%.0f dB SPL)"
          % (noise_rms, config.dbfs(noise_rms), config.spl(noise_rms)))
    print("              worst  %8.0f  (%.1f dBFS)  <- the number that matters"
          % (noise_max, config.dbfs(noise_max)))
    print("              spread p50->p99 %.1f dB, p50->max %.1f dB"
          % (config.dbfs(noise_pct["p99"]) - config.dbfs(noise_rms),
             config.dbfs(noise_max) - config.dbfs(noise_rms)))
    save_results()


def measure_speech():
    global speech_rms, speech_peak, speech_pct
    countdown("Say 'Hey Pico'", "over and over")
    vals, _ = collect("SPEECH", "keep talking...")
    speech_pct = percentiles(vals)
    # The top decile is what a wake word actually looks like: most frames of
    # any utterance are the quiet parts between syllables.
    speech_peak = vals[-1]
    speech_rms = vals[int(len(vals) * 0.9)]
    print("speech      : top-decile %8.0f  (%.1f dBFS, ~%.0f dB SPL)"
          % (speech_rms, config.dbfs(speech_rms), config.spl(speech_rms)))
    print("              peak       %8.0f  (%.1f dBFS)"
          % (speech_peak, config.dbfs(speech_peak)))
    save_results()


def measure_clip():
    global clip_peak
    countdown("Speak LOUDLY", "as loud as youll go")
    _, clip_peak = collect("CLIP", "be loud!")
    pct = clip_peak / config.FULL_SCALE * 100
    print("headroom    : peak sample %d = %.1f%% of full scale" % (clip_peak, pct))
    if pct > 90:
        print("              CLIPPING -- back off or the spectrum is garbage")
    save_results()


def measure_spectrum():
    global noise_bands
    countdown("Be QUIET again", "noise spectrum")
    acc = [0.0] * BANDS
    count = 0
    for f in range(FRAMES // 2):
        n = mic.readinto(raw)
        c = n // 4
        words = struct.unpack("<%di" % c, raw[:c * 4])
        total = 0
        for w in words:
            total += w >> 8
        dc = total / c
        for i in range(N):
            s = ((words[i] >> 8) - dc) if i < c else 0.0
            re[i] = s * window[i]
            im[i] = 0.0
        fft.run(re, im)
        for b in range(BANDS):
            e = 0.0
            for k in range(edges[b], edges[b + 1]):
                e += re[k] * re[k] + im[k] * im[k]
            acc[b] += e / (edges[b + 1] - edges[b])
        count += 1
        if f % 8 == 0:
            oled.fill(config.BLACK)
            oled.text("Lab 3: SPECTRUM", 0, 0, config.WHITE)
            oled.hline(0, 10, config.WIDTH, config.WHITE)
            oled.text("stay quiet...", 0, 22, config.WHITE)
            oled.rect(0, 46, config.WIDTH, 10, config.WHITE)
            filled = int((f + 1) / (FRAMES // 2) * (config.WIDTH - 4))
            if filled > 0:
                oled.fill_rect(2, 48, filled, 6, config.WHITE)
            oled.show()
    noise_bands = [a / count for a in acc]

    print("noise spectrum by band (Hz -> relative dB):")
    peak = max(noise_bands) or 1.0
    for b in range(BANDS):
        rel = 10 * math.log(noise_bands[b] / peak + 1e-12) / 2.302585092994046
        lo = int(edges[b] * bin_hz)
        hi = int(edges[b + 1] * bin_hz)
        bar = "#" * int(max(0, (rel + 40) / 40 * 20))
        print("  %5d-%5d Hz  %6.1f  %s" % (lo, hi, rel, bar))
    worst = noise_bands.index(peak)
    print("loudest noise band: %d-%d Hz"
          % (int(edges[worst] * bin_hz), int(edges[worst + 1] * bin_hz)))
    if worst <= 2:
        print("  -> low-frequency room rumble (HVAC, traffic).")
        print("     Consider raising BAND_LO_HZ in Lab 4 above %d Hz."
              % int(edges[worst + 1] * bin_hz))
    save_results()


def drain_mic():
    """Throw away everything the mic buffered while nothing was reading it.

    config.MIC_BUFFER_BYTES is 40000 bytes -- 781 ms of audio at this rate. The
    countdown reads nothing for 2.7 seconds, so by the time a measurement
    starts that buffer is full of whatever happened while you were reaching for
    the button: the click of the button itself, your hand passing the mic, a
    chair. Discarding a single frame leaves 761 ms of it to be measured as if
    it were the room, and since the gate is set from the WORST frame, one
    buffered button click is enough to wreck the recommendation.

    The buffered frames come back instantly; only the last couple block for
    real audio, so this costs a few tens of milliseconds.
    """
    for _ in range(config.MIC_BUFFER_BYTES // len(raw) + 4):
        poll_buttons()
        mic.readinto(raw)


def countdown(line1, line2):
    for c in (3, 2, 1):
        oled.fill(config.BLACK)
        oled.text(line1, 0, 12, config.WHITE)
        oled.text(line2, 0, 24, config.WHITE)
        oled.text("starting in %d" % c, 0, 44, config.WHITE)
        oled.show()
        for _ in range(9):      # 9 x 100 ms, so buttons stay responsive
            poll_buttons()
            time.sleep_ms(100)
    drain_mic()


def recommend():
    """A gate placed between the noise and the speech, in the log domain.

    The geometric mean sits halfway between them in dB, which is the right
    kind of halfway for a quantity measured in decibels. It is clamped to at
    least 4x the WORST noise frame, because the occasional loud frame in a
    "quiet" room is what actually causes false accepts -- not the median.
    """
    if noise_rms is None or speech_rms is None:
        return None
    floor = math.sqrt(noise_rms * speech_rms)
    if noise_max is not None and floor < noise_max * 4:
        floor = noise_max * 4
    if floor > speech_rms * 0.7:
        floor = speech_rms * 0.7        # never gate out your own voice
    return floor


def clamp_reason():
    """Which of recommend()'s three rules actually decided the floor.

    Worth recording, because the three mean very different things. The
    geometric mean is the healthy case. "4x-worst-noise-frame" means the
    room's loud outliers, not its average, set your gate. And
    "capped-at-0.7x-speech" means the outliers wanted a gate louder than your
    own voice -- the recommendation is a compromise, not a solution, and the
    room or the mic distance is what needs fixing.
    """
    if noise_rms is None or speech_rms is None:
        return None
    floor = math.sqrt(noise_rms * speech_rms)
    why = "geometric-mean"
    if noise_max is not None and floor < noise_max * 4:
        floor = noise_max * 4
        why = "4x-worst-noise-frame"
    if floor > speech_rms * 0.7:
        why = "capped-at-0.7x-speech"
    return why


def save_results():
    """Write every measurement taken so far to RESULTS_FILE on the Pico.

    Called after each measurement rather than only at the end, so a session
    that gets interrupted -- or a Pico that gets unplugged -- still leaves
    usable data behind. Fetch it with:

        mpremote connect <port> cp :calibration.json .

    Levels are stored as raw frame RMS values, with dBFS alongside, because
    the raw numbers are what config.py's SPEECH_FLOOR is expressed in and
    dBFS is what a human can reason about.
    """
    data = {
        "lab": 3,
        "schema": 2,
        "program": PROGRAM,
        "version": VERSION,
        "config_version": config.CONFIG_VERSION,
        "room_note": ROOM_NOTE,
        "uptime_ms": time.ticks_ms(),
        "config": {
            "sample_rate": config.SAMPLE_RATE,
            "fft_n": N,
            "frame_ms": FRAME_MS,
            "measure_ms": MEASURE_MS,
            "full_scale": config.FULL_SCALE,
            "spl_offset": config.SPL_OFFSET,
            "bands": BANDS,
            "band_lo_hz": BAND_LO_HZ,
            "band_hi_hz": BAND_HI_HZ,
            "asm_fft": ASM,
            "speech_floor_in_config": config.SPEECH_FLOOR / config.FULL_SCALE,
        },
        "timing": collect_stats,
        "noise": None,
        "speech": None,
        "clip": None,
        "spectrum": None,
        "recommended": None,
    }

    if noise_rms is not None:
        data["noise"] = {
            "median": noise_rms,
            "max": noise_max,
            "median_dbfs": config.dbfs(noise_rms),
            "max_dbfs": config.dbfs(noise_max),
            "median_spl": config.spl(noise_rms),
            "percentiles": noise_pct,
        }

    if speech_rms is not None:
        data["speech"] = {
            "top_decile": speech_rms,
            "peak": speech_peak,
            "top_decile_dbfs": config.dbfs(speech_rms),
            "peak_dbfs": config.dbfs(speech_peak),
            "top_decile_spl": config.spl(speech_rms),
            "percentiles": speech_pct,
        }

    if clip_peak is not None:
        data["clip"] = {
            "peak_sample": clip_peak,
            "percent_of_full_scale": clip_peak / config.FULL_SCALE * 100,
        }

    if noise_bands is not None:
        data["spectrum"] = {
            "edges_hz": [int(edges[b] * bin_hz) for b in range(BANDS + 1)],
            "energy": noise_bands,
        }

    floor = recommend()
    if floor is not None:
        data["recommended"] = {
            "speech_floor": floor,
            "speech_floor_fraction": floor / config.FULL_SCALE,
            "speech_floor_dbfs": config.dbfs(floor),
            "snr_db": config.dbfs(speech_rms) - config.dbfs(noise_rms),
            "set_by": clamp_reason(),
        }

    gc.collect()        # a measurement just built and dropped a 250-item list

    # THE MICROPHONE MUST BE CLOSED ACROSS THE FLASH WRITE.
    #
    # On the RP2, programming flash disables execute-in-place. For those few
    # milliseconds the chip cannot fetch instructions from flash at all. The
    # I2S microphone's DMA completion interrupt lives in flash, so if it fires
    # inside that window the CPU jumps to code it cannot read -- a hard fault.
    #
    # It does not raise. It does not print. The board stops dead mid-write and
    # stays dead through a soft reset, needing the USB cable pulled. The
    # symptom is a lab that runs one measurement, prints its numbers, and then
    # never responds to a button again -- which is exactly how this was found,
    # after mistakenly blaming the buttons for it.
    #
    # Closing the stream removes the interrupt source entirely. Reopening costs
    # a few milliseconds and an empty buffer, and every measurement drains the
    # buffer before collecting anyway.
    global mic
    mic.deinit()

    # Write to a temp file and rename it into place, rather than opening the
    # real file directly. open(path, "w") truncates IMMEDIATELY, so a stop
    # button pressed mid-write would leave a 0-byte or half-written file where
    # a good result used to be -- destroying the previous measurement and
    # producing something that is not even valid JSON. This way an interrupted
    # write costs only the temp file.
    tmp = RESULTS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        # MicroPython's rename will not overwrite on every filesystem, so clear
        # the target first. The gap between these two calls is the one moment
        # the file does not exist -- microseconds, against a write that takes
        # milliseconds.
        try:
            os.remove(RESULTS_FILE)
        except OSError:
            pass                            # first run: nothing to replace
        os.rename(tmp, RESULTS_FILE)
    except (OSError, MemoryError) as e:
        # Never fatal. The console output above is still the real result, and
        # losing the file must not cost you the measurement you just sat
        # through five seconds of silence for.
        print("WARNING: could not write %s (%s)" % (RESULTS_FILE, e))
        try:
            os.remove(tmp)
        except OSError:
            pass
    finally:
        # Always reopen, even if the write failed -- every later measurement
        # needs the microphone back.
        mic = config.init_microphone()


def clear_all():
    """Throw away every measurement and reset the results file.

    A mode of its own rather than a second button: the kit has two buttons and
    neither is spare, and making this take a deliberate walk through the whole
    mode list means five seconds of measured silence cannot be destroyed by a
    stray press.
    """
    global noise_rms, noise_max, noise_pct
    global speech_rms, speech_peak, speech_pct
    global clip_peak, noise_bands
    noise_rms = noise_max = noise_pct = None
    speech_rms = speech_peak = speech_pct = None
    clip_peak = None
    noise_bands = None
    save_results()
    print("cleared all measurements (and reset %s)" % RESULTS_FILE)


def draw():
    oled.fill(config.BLACK)
    oled.text("Lab 3: " + MODES[mode], 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)

    if mode == MODE_NOISE:
        if noise_rms is None:
            oled.text("Measures the", 0, 18, config.WHITE)
            oled.text("quiet room.", 0, 28, config.WHITE)
            oled.text("SELECT to run", 0, 46, config.WHITE)
        else:
            oled.text("med %.0f dBFS" % config.dbfs(noise_rms), 0, 18, config.WHITE)
            oled.text("max %.0f dBFS" % config.dbfs(noise_max), 0, 30, config.WHITE)
            oled.text("~%.0f dB SPL" % config.spl(noise_rms), 0, 42, config.WHITE)

    elif mode == MODE_SPEECH:
        if speech_rms is None:
            oled.text("Talk at your", 0, 18, config.WHITE)
            oled.text("normal spot.", 0, 28, config.WHITE)
            oled.text("SELECT to run", 0, 46, config.WHITE)
        else:
            oled.text("d90 %.0f dBFS" % config.dbfs(speech_rms), 0, 18, config.WHITE)
            oled.text("~%.0f dB SPL" % config.spl(speech_rms), 0, 30, config.WHITE)
            if noise_rms:
                snr = config.dbfs(speech_rms) - config.dbfs(noise_rms)
                oled.text("SNR %.0f dB" % snr, 0, 42, config.WHITE)

    elif mode == MODE_CLIP:
        if clip_peak is None:
            oled.text("Checks headroom", 0, 18, config.WHITE)
            oled.text("when you shout.", 0, 28, config.WHITE)
            oled.text("SELECT to run", 0, 46, config.WHITE)
        else:
            pct = clip_peak / config.FULL_SCALE * 100
            oled.text("peak %.1f%% FS" % pct, 0, 18, config.WHITE)
            oled.text("CLIPPING!" if pct > 90 else "headroom ok", 0, 32,
                      config.WHITE)

    elif mode == MODE_SPECTRUM:
        if noise_bands is None:
            oled.text("Where the room", 0, 18, config.WHITE)
            oled.text("noise lives.", 0, 28, config.WHITE)
            oled.text("SELECT to run", 0, 46, config.WHITE)
        else:
            peak = max(noise_bands) or 1.0
            w = config.WIDTH // BANDS
            for b in range(BANDS):
                h = int(noise_bands[b] / peak * 34)
                if h > 0:
                    oled.fill_rect(b * w, 50 - h, w - 1, h, config.WHITE)
            oled.text("low", 0, 54, config.WHITE)
            oled.text("high", 96, 54, config.WHITE)

    elif mode == MODE_CLEAR:
        oled.text("Discard every", 0, 18, config.WHITE)
        oled.text("measurement?", 0, 28, config.WHITE)
        oled.text("SELECT = yes", 0, 46, config.WHITE)

    else:  # MODE_RESULT
        floor = recommend()
        if floor is None:
            oled.text("Run NOISE and", 0, 18, config.WHITE)
            oled.text("SPEECH first.", 0, 28, config.WHITE)
        else:
            oled.text("SPEECH_FLOOR", 0, 16, config.WHITE)
            oled.text("%.5f" % (floor / config.FULL_SCALE), 0, 28, config.WHITE)
            oled.text("x FULL_SCALE", 0, 38, config.WHITE)
            snr = config.dbfs(speech_rms) - config.dbfs(noise_rms)
            oled.text("SNR %.0f dB" % snr, 0, 50, config.WHITE)

    oled.text("MODE=next", 60, 56, config.WHITE)
    oled.show()


def report():
    floor = recommend()
    save_results()
    print()
    print("=" * 58)
    print("CALIBRATION RESULT")
    print("=" * 58)
    if floor is None:
        print("Incomplete -- run at least the NOISE and SPEECH measurements.")
        print("You are on mode %s. Press MODE until the console says SPEECH,"
              % MODES[mode])
        print("then press SELECT and say 'Hey Pico' until the bar fills.")
        print("(partial results saved to %s)" % RESULTS_FILE)
        return
    snr = config.dbfs(speech_rms) - config.dbfs(noise_rms)
    print("room noise  : %.1f dBFS  (~%.0f dB SPL)"
          % (config.dbfs(noise_rms), config.spl(noise_rms)))
    print("your speech : %.1f dBFS  (~%.0f dB SPL)"
          % (config.dbfs(speech_rms), config.spl(speech_rms)))
    print("SNR         : %.1f dB" % snr)
    if snr < 15:
        print("  -> under 15 dB is a hard room. Move closer to the mic, or")
        print("     expect Lab 4's false-reject rate to be poor no matter")
        print("     what threshold you choose.")
    print()
    print("Paste this into config.py:")
    print()
    print("    SPEECH_FLOOR = FULL_SCALE * %.5f" % (floor / config.FULL_SCALE))
    print()
    print("(currently %.5f)" % (config.SPEECH_FLOOR / config.FULL_SCALE))
    print("That floor was set by the %s rule." % clamp_reason())
    print()
    print("Saved to %s. Copy it off the Pico with:" % RESULTS_FILE)
    print("    mpremote connect <port> cp :%s ." % RESULTS_FILE)
    print("or run ./get-results.sh from the labs directory.")


RUNNERS = [measure_noise, measure_speech, measure_clip, measure_spectrum,
           None, clear_all]

BAR = "=" * 62

print()
print(BAR)
print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("Lab 3: Microphone Calibration")
print(BAR)
print("Goal: measure SPEECH_FLOOR -- the loudness gate Lab 4 uses to tell")
print("'someone is talking' apart from 'the room is just sitting there'.")
print("Guessing it wrong looks like a bug somewhere else, in both")
print("directions: too high and the detector cannot hear you, too low and")
print("it scores silence all day.")
print()
print("BUTTONS:  MODE (GPIO %d) = next test    SELECT (GPIO %d) = run it"
      % (config.BUTTON_MODE_PIN, config.BUTTON_SELECT_PIN))
print("Each measurement takes %d seconds and draws a progress bar." % (MEASURE_MS // 1000))
print()
print("RUN THESE IN ORDER. NOISE and SPEECH are both required before RESULT")
print("can recommend anything -- the other two are diagnostics.")
print()
print("  1. NOISE     (you are here) stay quiet, press SELECT")
print("  2. MODE -> SPEECH     SELECT, then say 'Hey Pico' over and over")
print("  3. MODE -> CLIP       SELECT, then speak as loud as you ever would")
print("  4. MODE -> SPECTRUM   stay quiet, press SELECT")
print("  5. MODE -> RESULT     prints the line to paste into config.py")
print("  6. MODE -> CLEAR      only if you want to discard it all and restart")
print()
print("Measure in the room, and at the distance, you will actually use.")
print("ROOM_NOTE is currently:")
print("    %s" % ROOM_NOTE)
print("Edit ROOM_NOTE at the top of this file if that is not right.")
print()
print("Results are written to %s after EVERY measurement, so an" % RESULTS_FILE)
print("interrupted session still leaves usable data on the Pico. Copy it off")
print("with:  mpremote connect <port> cp :%s ." % RESULTS_FILE)
print(BAR)
print()
announce(MODE_NOISE)

for _ in range(5):                        # settle the microphone
    mic.readinto(raw)
    time.sleep_ms(20)

draw()

try:
    while True:
        if took("mode"):
            mode = (mode + 1) % len(MODES)
            announce(mode)
            if mode == MODE_RESULT:
                report()
            draw()

        elif took("select"):
            # RESULT is the one mode with no runner -- SELECT reprints instead.
            if RUNNERS[mode] is not None:
                RUNNERS[mode]()
            else:
                report()
            draw()

        time.sleep_ms(20)

except KeyboardInterrupt:
    mic.deinit()
    report()
    oled.fill(config.BLACK)
    oled.text("Stopped.", 30, 28, config.WHITE)
    oled.show()
