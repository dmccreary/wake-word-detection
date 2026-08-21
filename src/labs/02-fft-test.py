# Lab 2: FFT Test -- can this board do the signal processing in real time?
#
# Lab 4 needs to turn a live microphone stream into a sequence of spectra,
# forever, without ever missing a sample. Before writing that, measure whether
# the chip can actually do it. This lab answers one question with a number:
#
#     How much of one audio frame's time budget does an FFT consume?
#
# The budget is not a matter of opinion. At 12800 Hz, 256 samples IS 20 ms of
# sound. If the FFT of one frame takes longer than 20 ms, the next frame's
# audio arrives while you are still working on the last one, and it is gone.
#
# Both FFT implementations come from the prerequisite course:
#   fftlab.FFT    -- the pure-Python FFT built in that course's Lab 20
#   fft_asm.FFT   -- the same algorithm with its butterflies in ARM assembly
#
# Run this on real captured audio, not a synthetic tone, so the measurement
# includes the capture step the real pipeline will also have to pay for.

import gc
import time

import config

PROGRAM = "02-fft-test"
VERSION = "1.0.0"
import dwt_timer
import fftlab

N = 256                         # feature FFT size used by Lab 4
FRAME_MS = N / config.SAMPLE_RATE * 1000
TRIALS = 10

try:
    import fft_asm
    HAVE_ASM = True
except (ImportError, SyntaxError) as e:
    # asm_thumb is a compile-time feature. A build without FPU assembly support
    # raises at import, and that is a real finding, not a crash to hide.
    HAVE_ASM = False
    ASM_ERROR = e

oled = config.init_display()


def show(lines):
    oled.fill(config.BLACK)
    oled.text("Lab 2: FFT Test", 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)
    for i, line in enumerate(lines[:5]):
        oled.text(line, 0, 16 + i * 10, config.WHITE)
    oled.show()


def capture_frame():
    """One frame of real audio from the microphone."""
    mic = config.init_microphone()
    raw = bytearray(N * 4)
    settle = bytearray(N * 4)
    for _ in range(5):
        mic.readinto(settle)
        time.sleep_ms(20)
    samples = config.read_samples(mic, raw, N)
    mic.deinit()
    return samples


def time_capture():
    """How long one readinto() of a full frame blocks for.

    This should come out close to FRAME_MS -- the mic delivers audio in real
    time, so waiting for 20 ms of sound takes 20 ms. It is measured anyway,
    because 'should' is not 'did'.
    """
    mic = config.init_microphone()
    raw = bytearray(N * 4)
    for _ in range(5):
        mic.readinto(raw)
    t0 = time.ticks_us()
    for _ in range(TRIALS):
        mic.readinto(raw)
    t1 = time.ticks_us()
    mic.deinit()
    return time.ticks_diff(t1, t0) / TRIALS / 1000.0


def bench(name, fft, load, run, samples):
    """One discarded warm-up, then TRIALS timed runs. Report the mean.

    The warm-up is discarded because the first call pays one-time costs that
    the steady-state pipeline will not. The buffers are reloaded every trial
    because the transform is in place and consumes its input.
    """
    re, im = load()
    for i in range(N):
        re[i] = samples[i]
        im[i] = 0.0
    run(re, im)                          # warm-up, discarded

    total = 0
    best = None
    for _ in range(TRIALS):
        for i in range(N):
            re[i] = samples[i]
            im[i] = 0.0
        gc.collect()                     # keep the GC out of the timed window
        t0 = time.ticks_us()
        run(re, im)
        t1 = time.ticks_us()
        us = time.ticks_diff(t1, t0)
        total += us
        if best is None or us < best:
            best = us
    return total / TRIALS / 1000.0, best / 1000.0


print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("Lab 2: FFT Test")
print("N = %d at %d Hz -> one frame is %.1f ms of sound" %
      (N, config.SAMPLE_RATE, FRAME_MS))
print()

show(["N=%d @ %dHz" % (N, config.SAMPLE_RATE),
      "budget %.1f ms" % FRAME_MS, "", "capturing..."])

mhz = dwt_timer.verify()
print("DWT cycle counter: %.2f MHz" % mhz)
if mhz < 1.0:
    print("WARNING: cycle counter stalled; trusting time.ticks_us() only")
print()

capture_ms = time_capture()
samples = capture_frame()
peak = max(abs(s) for s in samples)
print("captured %d samples, peak %.2f%% of full scale" %
      (N, peak / config.FULL_SCALE * 100))
print("mic readinto(): %.2f ms per frame (expected ~%.1f)" %
      (capture_ms, FRAME_MS))
print()

results = []

show(["running", "pure Python", "FFT...", "(this is slow)"])
py = fftlab.FFT(N)
mean, best = bench("python", py, py.buffers, py.run, samples)
results.append(("pure Python", mean, best))
print("pure Python FFT : mean %8.2f ms   best %8.2f ms" % (mean, best))

if HAVE_ASM:
    show(["running", "assembly", "FFT..."])
    asm = fft_asm.FFT(N)
    mean, best = bench("asm", asm, asm.make_buffers, asm.run, samples)
    results.append(("assembly", mean, best))
    print("assembly FFT    : mean %8.2f ms   best %8.2f ms" % (mean, best))
else:
    print("assembly FFT    : unavailable on this build (%s)" % ASM_ERROR)

print()
print("=== Verdict against a %.1f ms frame budget ===" % FRAME_MS)
print("%-14s %10s %10s %12s" % ("implementation", "mean ms", "% budget",
                                "real time?"))
print("-" * 50)

verdict_lines = []
for name, mean, best in results:
    pct = mean / FRAME_MS * 100
    # Capture and the FFT both have to fit inside one frame, and so does the
    # comparison work Lab 4 adds on top. Anything above ~50% of the budget has
    # no room left for the rest of the pipeline.
    ok = "YES" if pct < 50 else ("TIGHT" if pct < 100 else "NO")
    print("%-14s %10.2f %9.1f%% %12s" % (name, mean, pct, ok))
    verdict_lines.append("%s %.0f%% %s" % (name[:6], pct, ok))

print()
if HAVE_ASM and results[-1][1] / FRAME_MS < 0.5:
    headroom = FRAME_MS / results[-1][1]
    print("The assembly FFT fits %.0fx over inside one frame." % headroom)
    print("Lab 4's continuous pipeline is therefore comfortably possible.")
else:
    print("Nothing measured here leaves room for a continuous pipeline.")
    print("Lab 4 will drop frames on this build -- that is a real result,")
    print("and the honest fix is a faster FFT, not a smaller budget.")

show(["budget %.1f ms" % FRAME_MS] + verdict_lines)
