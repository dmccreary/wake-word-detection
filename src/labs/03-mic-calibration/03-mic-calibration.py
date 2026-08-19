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
# So measure it. Five modes, MODE to advance, UP to start/restart the current
# measurement, DOWN to clear everything:
#
#   0 NOISE    the room with nobody talking
#   1 SPEECH   you, at the distance you will actually use
#   2 CLIP     headroom check -- are you overloading the microphone?
#   3 SPECTRUM which bands the room's noise actually occupies
#   4 RESULT   the SPEECH_FLOOR to paste into config.py
#
# Nothing here is real-time critical, so unlike Lab 4 this lab draws freely.

import math
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

BANDS = 12                               # must match Lab 4
BAND_LO_HZ = 150
BAND_HI_HZ = 6000

MODES = ["NOISE", "SPEECH", "CLIP", "SPECTRUM", "RESULT"]
MODE_NOISE, MODE_SPEECH, MODE_CLIP, MODE_SPECTRUM, MODE_RESULT = range(5)

oled = config.init_display()
button_mode, button_up, button_down = config.init_buttons()
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
speech_rms = None       # median frame RMS while talking
speech_peak = None      # loudest frame while talking
clip_peak = None        # largest raw sample magnitude
noise_bands = None      # per-band noise energy

mode = MODE_NOISE
last = [button_mode.value(), button_up.value(), button_down.value()]
last_press_ms = time.ticks_ms()


def pressed(pin, previous):
    return previous == 1 and pin.value() == 0


def frame_rms():
    """One frame: return (rms of the AC part, peak absolute sample)."""
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
    return math.sqrt(energy / count), peak


def collect(label, seconds_note):
    """Run one measurement for MEASURE_MS, returning sorted frame RMS values.

    Returns (sorted_rms_list, peak_sample). A progress bar is drawn between
    frames -- the mic keeps buffering during the redraw, and since this lab is
    not doing continuous detection a few dropped frames cost nothing.
    """
    values = []
    peak_sample = 0
    for f in range(FRAMES):
        r, p = frame_rms()
        values.append(r)
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
    values.sort()
    return values, peak_sample


def median(sorted_values):
    return sorted_values[len(sorted_values) // 2]


def measure_noise():
    global noise_rms, noise_max
    countdown("Be QUIET", "measuring room")
    vals, _ = collect("NOISE", "stay quiet...")
    noise_rms = median(vals)
    noise_max = vals[-1]
    print("noise floor : median %8.0f  (%.1f dBFS, ~%.0f dB SPL)"
          % (noise_rms, config.dbfs(noise_rms), config.spl(noise_rms)))
    print("              worst  %8.0f  (%.1f dBFS)  <- the number that matters"
          % (noise_max, config.dbfs(noise_max)))


def measure_speech():
    global speech_rms, speech_peak
    countdown("Say 'Hey Pico'", "over and over")
    vals, _ = collect("SPEECH", "keep talking...")
    # The top decile is what a wake word actually looks like: most frames of
    # any utterance are the quiet parts between syllables.
    speech_peak = vals[-1]
    speech_rms = vals[int(len(vals) * 0.9)]
    print("speech      : top-decile %8.0f  (%.1f dBFS, ~%.0f dB SPL)"
          % (speech_rms, config.dbfs(speech_rms), config.spl(speech_rms)))
    print("              peak       %8.0f  (%.1f dBFS)"
          % (speech_peak, config.dbfs(speech_peak)))


def measure_clip():
    global clip_peak
    countdown("Speak LOUDLY", "as loud as youll go")
    _, clip_peak = collect("CLIP", "be loud!")
    pct = clip_peak / config.FULL_SCALE * 100
    print("headroom    : peak sample %d = %.1f%% of full scale" % (clip_peak, pct))
    if pct > 90:
        print("              CLIPPING -- back off or the spectrum is garbage")


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


def countdown(line1, line2):
    for c in (3, 2, 1):
        oled.fill(config.BLACK)
        oled.text(line1, 0, 12, config.WHITE)
        oled.text(line2, 0, 24, config.WHITE)
        oled.text("starting in %d" % c, 0, 44, config.WHITE)
        oled.show()
        time.sleep_ms(900)
    mic.readinto(raw)          # discard whatever buffered during the countdown


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


def draw():
    oled.fill(config.BLACK)
    oled.text("Lab 3: " + MODES[mode], 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)

    if mode == MODE_NOISE:
        if noise_rms is None:
            oled.text("Measures the", 0, 18, config.WHITE)
            oled.text("quiet room.", 0, 28, config.WHITE)
            oled.text("UP to start", 0, 46, config.WHITE)
        else:
            oled.text("med %.0f dBFS" % config.dbfs(noise_rms), 0, 18, config.WHITE)
            oled.text("max %.0f dBFS" % config.dbfs(noise_max), 0, 30, config.WHITE)
            oled.text("~%.0f dB SPL" % config.spl(noise_rms), 0, 42, config.WHITE)

    elif mode == MODE_SPEECH:
        if speech_rms is None:
            oled.text("Talk at your", 0, 18, config.WHITE)
            oled.text("normal spot.", 0, 28, config.WHITE)
            oled.text("UP to start", 0, 46, config.WHITE)
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
            oled.text("UP to start", 0, 46, config.WHITE)
        else:
            pct = clip_peak / config.FULL_SCALE * 100
            oled.text("peak %.1f%% FS" % pct, 0, 18, config.WHITE)
            oled.text("CLIPPING!" if pct > 90 else "headroom ok", 0, 32,
                      config.WHITE)

    elif mode == MODE_SPECTRUM:
        if noise_bands is None:
            oled.text("Where the room", 0, 18, config.WHITE)
            oled.text("noise lives.", 0, 28, config.WHITE)
            oled.text("UP to start", 0, 46, config.WHITE)
        else:
            peak = max(noise_bands) or 1.0
            w = config.WIDTH // BANDS
            for b in range(BANDS):
                h = int(noise_bands[b] / peak * 34)
                if h > 0:
                    oled.fill_rect(b * w, 50 - h, w - 1, h, config.WHITE)
            oled.text("low", 0, 54, config.WHITE)
            oled.text("high", 96, 54, config.WHITE)

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
    print()
    print("=" * 58)
    print("CALIBRATION RESULT")
    print("=" * 58)
    if floor is None:
        print("Incomplete -- run at least the NOISE and SPEECH measurements.")
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
    print("Record the room and distance you measured in -- a false-accept")
    print("rate without its noise environment is not a result.")


RUNNERS = [measure_noise, measure_speech, measure_clip, measure_spectrum, None]

print("Lab 3: Microphone Calibration")
print("MODE cycles tests, UP runs the current one, DOWN clears all.")
print("Each measurement takes %d seconds.\n" % (MEASURE_MS // 1000))

for _ in range(5):                        # settle the microphone
    mic.readinto(raw)
    time.sleep_ms(20)

draw()

try:
    while True:
        now = time.ticks_ms()
        settled = time.ticks_diff(now, last_press_ms) > config.DEBOUNCE_MS

        if settled and pressed(button_mode, last[0]):
            mode = (mode + 1) % len(MODES)
            last_press_ms = now
            if mode == MODE_RESULT:
                report()
            draw()

        elif settled and pressed(button_up, last[1]):
            last_press_ms = now
            if RUNNERS[mode] is not None:
                RUNNERS[mode]()
            else:
                report()
            draw()

        elif settled and pressed(button_down, last[2]):
            last_press_ms = now
            noise_rms = noise_max = None
            speech_rms = speech_peak = None
            clip_peak = None
            noise_bands = None
            print("cleared all measurements")
            draw()

        last = [button_mode.value(), button_up.value(), button_down.value()]
        time.sleep_ms(30)

except KeyboardInterrupt:
    mic.deinit()
    report()
    oled.fill(config.BLACK)
    oled.text("Stopped.", 30, 28, config.WHITE)
    oled.show()
