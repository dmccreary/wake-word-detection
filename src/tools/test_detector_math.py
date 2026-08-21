"""Host-side check of Lab 4's detector math. Runs on a laptop, not the Pico.

    python3 src/tools/test_detector_math.py

Every number quoted in the Lab 4 writeup comes from this script. It imports the
REAL 04-wake-word-test.py -- stubbing out `machine`, `ssd1306` and `fft_asm` --
and drives its own feature_frame(), push(), window_score() and
rebuild_template() with synthetic speech. Reimplementing the math here would
risk testing something other than what ships, so it deliberately does not.

What it checks:
  * the enrolled phrase scores far above an impostor built from the same sounds
    in a different order (proves temporal order matters, not just spectrum)
  * silence is rejected by the loudness gate rather than by score alone
  * the score falls off as the spoken phrase fills less of the fixed window --
    the time-warping limitation, measured rather than asserted

Run it after ANY change to feature extraction or scoring. The failure signature
worth knowing: if every row scores ~1.00, the per-frame mean log-energy
subtraction has been lost, and the detector has no discriminative power at all.
"""
import math
import random
import struct
import sys
import types

import os
SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC + "/labs/lib")

FULL_SCALE = 8388608
SAMPLE_RATE = 12800

# ---- fake machine / ssd1306 so config.py imports cleanly -------------------
machine = types.ModuleType("machine")


class _Pin:
    IN = OUT = PULL_UP = 0

    def __init__(self, *a, **k):
        self._v = 1

    def value(self, *a):
        return self._v

    def on(self):
        pass

    def off(self):
        pass

    def toggle(self):
        pass


class _SPI:
    def __init__(self, *a, **k):
        pass


class _I2S:
    RX = TX = MONO = 0

    def __init__(self, *a, **k):
        pass

    def readinto(self, buf):
        return len(buf)

    def write(self, buf):
        return len(buf)

    def deinit(self):
        pass


machine.Pin = _Pin
machine.SPI = _SPI
machine.I2S = _I2S
sys.modules["machine"] = machine

ssd1306 = types.ModuleType("ssd1306")


class _OLED:
    def __getattr__(self, name):
        return lambda *a, **k: None


ssd1306.SSD1306_SPI = lambda *a, **k: _OLED()
sys.modules["ssd1306"] = ssd1306

# ---- fake fft_asm that delegates to the pure-Python FFT --------------------
import fftlab

fft_asm = types.ModuleType("fft_asm")


class _FFT(fftlab.FFT):
    def make_buffers(self):
        return self.buffers()


fft_asm.FFT = _FFT
sys.modules["fft_asm"] = fft_asm

sys.path.insert(0, SRC)
sys.path.insert(0, SRC + "/labs")
sys.path.insert(0, SRC + "/labs/lib")

# ---- import the real lab ---------------------------------------------------
import importlib.util

spec = importlib.util.spec_from_file_location(
    "lab3", SRC + "/labs/04-wake-word-test.py")
lab3 = importlib.util.module_from_spec(spec)

# The lab ends in an infinite loop; stop it the way a user would.
real_ticks_ms = None


class _StopLoop(Exception):
    pass


import time as _time
_orig_sleep = _time.sleep_ms if hasattr(_time, "sleep_ms") else None
_time.sleep_ms = lambda ms: None
_time.ticks_ms = lambda: int(_time.time() * 1000)
_time.ticks_us = lambda: int(_time.time() * 1000000)
_time.ticks_diff = lambda a, b: a - b
_time.ticks_add = lambda a, b: a + b

# Make the main loop exit immediately on its first iteration.
_time.sleep_ms = lambda ms: (_ for _ in ()).throw(KeyboardInterrupt)

try:
    spec.loader.exec_module(lab3)
except KeyboardInterrupt:
    pass
except Exception as e:
    print("lab import raised:", type(e).__name__, e)
    raise

print("loaded lab3: N=%d BANDS=%d TEMPLATE_FRAMES=%d threshold=%.2f"
      % (lab3.N, lab3.BANDS, lab3.TEMPLATE_FRAMES, lab3.THRESHOLD_START))
print("band edges (Hz):",
      [round(e * SAMPLE_RATE / lab3.N) for e in lab3.edges])

N = lab3.N
TF = lab3.TEMPLATE_FRAMES


# ---- synthetic phrases -----------------------------------------------------
def synth(recipe, jitter=0.03, amp=0.25, noise=0.02, seed=0, fill=1.0):
    """recipe segments are FRACTIONS of the window, so the phrase scales with
    TEMPLATE_FRAMES instead of being hardcoded to 32 frames.

    fill<1.0 simulates a phrase shorter than the window: the remainder is room
    noise, which is what actually happens when an 800 ms window holds a 650 ms
    phrase.
    """
    rng = random.Random(seed)
    span = TF * fill
    jit = [(lo * span, hi * span,
            [hz * (1 + jitter * rng.uniform(-1, 1)) for hz in fs])
           for lo, hi, fs in recipe]
    frames = []
    for f in range(TF):
        tones = []
        for lo, hi, fs in jit:
            if lo <= f < hi:
                tones = fs
        buf = bytearray(N * 4)
        for i in range(N):
            t = (f * N + i) / SAMPLE_RATE
            v = sum(math.sin(2 * math.pi * hz * t + k) / (k + 1)
                    for k, hz in enumerate(tones))
            v = v * amp * FULL_SCALE + rng.gauss(0, noise * FULL_SCALE)
            # pack as the INMP441 would: 24-bit audio in the top of a 32-bit word
            struct.pack_into("<i", buf, i * 4, int(v) << 8)
        frames.append(buf)
    return frames


def quiet(seed=0, spl=40.0):
    """Room tone at a given sound-pressure level.

    The INMP441 is -26 dBFS at 94 dB SPL, so dBFS = SPL - 120. 40 dB SPL is an
    ordinary quiet room; 60 dB SPL is a noticeably noisy one. Getting this level
    right matters: a synthetic "silence" that is secretly 60 dB SPL will sail
    through the loudness gate and make the gate look broken when it is not.
    """
    sigma = FULL_SCALE * 10 ** ((spl - 120) / 20)
    rng = random.Random(seed)
    frames = []
    for f in range(TF):
        buf = bytearray(N * 4)
        for i in range(N):
            struct.pack_into("<i", buf, i * 4, int(rng.gauss(0, sigma)) << 8)
        frames.append(buf)
    return frames


# Feed the lab's own feature_frame() by swapping the module-level `raw` buffer.
def feed(frames):
    """Push a whole phrase through the lab's real pipeline; return (score,rms)."""
    peak = 0.0
    for buf in frames:
        lab3.raw[:] = buf
        vec, rms = lab3.feature_frame()
        peak = max(peak, rms)
        lab3.push(vec, rms)
    return lab3.window_score(), peak


# fractions of the window: "Hey" | "Pee" | "Ko"
WAKE      = [(0.0, 0.31, [500, 1800]), (0.31, 0.63, [300, 2400]), (0.63, 1.0, [600, 1100])]
OTHER     = [(0.0, 0.50, [700, 1200]), (0.50, 1.0, [400, 2900])]
SCRAMBLED = [(0.0, 0.31, [600, 1100]), (0.31, 0.63, [300, 2400]), (0.63, 1.0, [500, 1800])]

# ---- enroll using the lab's own accumulator --------------------------------
for seed in (1, 2, 3, 4):
    frames = synth(WAKE, seed=seed)
    for f, buf in enumerate(frames):
        lab3.raw[:] = buf
        vec, _ = lab3.feature_frame()
        for b in range(lab3.BANDS):
            lab3.template_sum[f][b] += vec[b]
    lab3.enrollments += 1
lab3.rebuild_template()
print("\nenrolled %d takes of the wake phrase\n" % lab3.enrollments)

print("%-38s %8s %10s  %s" % ("test signal", "score", "peak rms", "gate"))
print("-" * 72)
results = {}
for name, recipe, seed, fill in [
    ("enrolled phrase, unseen take", WAKE, 99, 1.0),
    ("enrolled phrase, another take", WAKE, 123, 1.0),
    # realistic: a ~650 ms phrase inside an 800 ms window, trailing room noise
    ("enrolled phrase, 90% window fill", WAKE, 54, 0.90),
    ("enrolled phrase, 80% window fill *", WAKE, 55, 0.80),
    ("enrolled phrase, 65% window fill *", WAKE, 56, 0.65),
    ("different phrase", OTHER, 7, 1.0),
    ("same sounds, scrambled order", SCRAMBLED, 11, 1.0),
]:
    lab3.frames_seen = 0
    s, rms = feed(synth(recipe, seed=seed, fill=fill))
    results[name] = s
    gate = "speech" if rms > lab3.SPEECH_FLOOR else "GATED"
    print("%-38s %8.3f %10.0f  %s" % (name, s, rms, gate))

for label, spl_db in [("quiet room (40 dB SPL)", 40.0),
                      ("noisy room (60 dB SPL)", 60.0)]:
    lab3.frames_seen = 0
    s, rms = feed(quiet(spl=spl_db))
    results[label] = s
    gated = rms <= lab3.SPEECH_FLOOR
    if gated:
        gate = "GATED (good)"
    else:
        # Passing the gate is not automatically a failure -- the score still has
        # to clear the threshold. A loud room SHOULD reach the scorer; what
        # matters is that it scores far below an enrolled phrase.
        gate = "passes gate, score %s" % ("OK" if s < lab3.THRESHOLD_START
                                          else "TOO HIGH!")
    print("%-38s %8.3f %10.0f  %s" % (label, s, rms, gate))

# The supported envelope is >=90% window fill; the 80%/65% rows are the
# documented time-warping limitation, deliberately outside it.
match = min(results["enrolled phrase, unseen take"],
            results["enrolled phrase, another take"],
            results["enrolled phrase, 90% window fill"])
impostor = max(results["different phrase"],
               results["same sounds, scrambled order"])
print("\n=== verdict at the lab's default threshold %.2f ==="
      % lab3.THRESHOLD_START)
print("worst enrolled score : %.3f  -> %s"
      % (match, "ACCEPT" if match >= lab3.THRESHOLD_START else "REJECT (miss)"))
print("best impostor score  : %.3f  -> %s"
      % (impostor,
         "ACCEPT (false)" if impostor >= lab3.THRESHOLD_START else "REJECT"))
print("margin               : %.3f" % (match - impostor))
ok = match >= lab3.THRESHOLD_START > impostor
print("\ndefault threshold separates the cases:", "YES" if ok else "NO")
print("\n* rows marked with an asterisk are OUTSIDE the supported envelope:")
print("  a fixed-length template has no time warping, so a phrase spoken well")
print("  faster than it was enrolled cannot be recognized. The lab reports")
print("  window-fill %% at enrollment so the user can correct their pace.")
