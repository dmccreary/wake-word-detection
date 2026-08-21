# Diagnostic: is the microphone actually delivering audio at SAMPLE_RATE?
#
# Lab 3's progress bar should take exactly 5 seconds to fill: 250 frames of 256
# samples at 12800 Hz. If it finishes noticeably sooner, mic.readinto() is
# coming back short, and every measurement is computed from less audio than it
# claims. That corrupts levels quietly -- nothing errors, the numbers are just
# drawn from the wrong amount of sound.
#
# This reads frames exactly the way Lab 3 does and reports what really
# happened. It takes about five seconds and changes nothing.
#
# Run it, then read the last line.

import time

import config

PROGRAM = "00-mic-throughput"
VERSION = "1.0.0"

N = 256
FRAMES = 250
EXPECTED_MS = int(FRAMES * N / config.SAMPLE_RATE * 1000)

mic = config.init_microphone()
raw = bytearray(N * 4)

print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("Microphone throughput probe")
print("expecting %d frames x %d samples at %d Hz = %d ms"
      % (FRAMES, N, config.SAMPLE_RATE, EXPECTED_MS))
print("reading...")

# The first reads after opening an I2S stream can return whatever was already
# buffered, so they are not representative of steady-state throughput.
for _ in range(5):
    mic.readinto(raw)

counts = {}
t0 = time.ticks_ms()
for _ in range(FRAMES):
    n = mic.readinto(raw)
    counts[n] = counts.get(n, 0) + 1
elapsed = time.ticks_diff(time.ticks_ms(), t0)

total_samples = 0
for n in counts:
    total_samples += (n // 4) * counts[n]

print()
print("elapsed        : %d ms   (expected %d ms)" % (elapsed, EXPECTED_MS))
sizes = sorted(counts.keys())
print("bytes per read : %s"
      % ", ".join("%d bytes x%d" % (n, counts[n]) for n in sizes))
print("total samples  : %d   (expected %d)" % (total_samples, FRAMES * N))
if elapsed > 0:
    print("effective rate : %d Hz   (configured %d Hz)"
          % (total_samples * 1000 // elapsed, config.SAMPLE_RATE))
print()

if elapsed < EXPECTED_MS * 0.8:
    print("SHORT -- the mic returned less audio than asked for.")
    print("Every Lab 3 measurement covers less time than its bar claims, so")
    print("the levels it reports are drawn from the wrong amount of sound.")
elif elapsed > EXPECTED_MS * 1.2:
    print("SLOW -- frames arrive slower than the configured rate.")
    print("Something upstream is stalling the I2S stream.")
elif total_samples != FRAMES * N:
    print("PARTIAL -- the timing is right but some reads came back short.")
else:
    print("OK -- full frames arriving at the configured rate.")
    print("A progress bar that felt fast was simply five seconds feeling")
    print("short. Nothing is wrong with the microphone path.")

mic.deinit()
