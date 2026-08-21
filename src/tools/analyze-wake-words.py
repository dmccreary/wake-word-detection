#!/usr/bin/env python3
"""Read the WAV takes from record-wake-words.py and say what they mean.

    python3 src/tools/analyze-wake-words.py sounds/

Lab 4 can only report what it already believes -- a score, a threshold, an RMS
it measured with settings that may themselves be wrong. These recordings are
the raw material instead, so the questions the board keeps begging can be
answered by measurement rather than by another guess:

  * How long is the phrase, really? -> TEMPLATE_FRAMES
  * How loud is it, really, take to take? -> SPEECH_FLOOR
  * Where does its energy actually sit? -> BAND_LO_HZ

The last one is the reason this exists. Lab 3 measures a NOISE spectrum, so
until something measured a SPEECH spectrum the band edges were an assumption.
Point this at a folder of takes and it becomes a number.

Pass a calibration.json as the second argument to compare the speech spectrum
against the room noise Lab 3 measured -- that comparison is what decides
BAND_LO_HZ, because a band is only worth keeping if speech beats noise in it.

Runs on a host, not the Pico. Needs numpy.
"""

import json
import os
import sys
import wave

import numpy as np

# These MUST match Lab 4, or the answer is about some other detector.
N = 256
RATE = 12800
BANDS = 12
BAND_LO_HZ = 150
BAND_HI_HZ = 6000

# record-wake-words.py amplifies on the way to 16 bits so the files are not all
# crammed into the bottom of their range. Undoing it here puts every level back
# into the 24-bit units that calibration.json and Lab 4's console both use.
GAIN = 4

RAMP = " .:-=+*#%@"


def band_edges():
    """Lab 4's log-spaced band edges, recomputed exactly as the lab does."""
    bin_hz = RATE / N
    lo = max(1, int(BAND_LO_HZ / bin_hz))
    hi = min(N // 2 - 1, int(BAND_HI_HZ / bin_hz))
    ratio = (hi / lo) ** (1.0 / BANDS)
    edges = [int(lo * ratio ** b) for b in range(BANDS + 1)]
    for b in range(BANDS):
        if edges[b + 1] <= edges[b]:
            edges[b + 1] = edges[b] + 1
    return edges


def load(path):
    """One take, as float samples in 24-bit units, framed like the detector."""
    with wave.open(path, "rb") as w:
        if w.getframerate() != RATE:
            print("  warning: %s is %d Hz, expected %d"
                  % (path, w.getframerate(), RATE))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    x = x.astype(np.float64) * GAIN
    return x[:len(x) // N * N].reshape(-1, N)


def frame_rms(frames):
    return np.sqrt((frames * frames).mean(axis=1))


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "sounds"
    calib = sys.argv[2] if len(sys.argv) > 2 else None

    names = sorted(f for f in os.listdir(folder) if f.endswith(".wav"))
    if not names:
        print("no .wav files in %s" % folder)
        return 1

    takes = [(n, load(os.path.join(folder, n))) for n in names]
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / (N - 1))
    edges = band_edges()
    hz = [e * RATE / N for e in edges]

    # ---- envelopes -------------------------------------------------------
    print("=" * 72)
    print("ENVELOPE -- one character per %.0f ms frame, each take scaled to itself"
          % (N / RATE * 1000))
    print("=" * 72)
    for name, f in takes:
        rms = np.maximum(frame_rms(f), 1e-9)
        db = 20 * np.log10(rms)
        lo, hi = np.percentile(db, 20), db.max()
        span = max(hi - lo, 1e-9)
        print("%s" % name)
        print("  " + "".join(
            RAMP[min(9, max(0, int((d - lo) / span * 9.999)))] for d in db))

    # ---- how long is the phrase -----------------------------------------
    #
    # Gated at 10 dB above each take's own noise floor rather than at a fixed
    # level. A fixed gate is exactly the mistake that made Lab 4's fill
    # percentage meaningless: set it below the room and silence reads as
    # speech, set it near the peak and only the loudest vowel survives.
    print()
    print("=" * 72)
    print("PHRASE EXTENT -- gate at noise floor + 10 dB")
    print("=" * 72)
    print("take                  floor  peak frame   first  last  frames    ms")
    spans = []
    peaks = []
    floors = []
    for name, f in takes:
        rms = frame_rms(f)
        floor = np.percentile(rms, 20)
        on = np.where(rms > floor * 3.162)[0]
        if not len(on):
            print("  %-20s  %5.0f  no frames above gate" % (name, floor))
            continue
        span = on[-1] - on[0] + 1
        spans.append(span)
        peaks.append(rms.max())
        floors.append(floor)
        print("  %-20s  %5.0f  %10.0f   %5d %5d  %6d %5.0f"
              % (name, floor, rms.max(), on[0], on[-1], span, span * N / RATE * 1000))

    spans = np.array(spans)
    print()
    print("  span frames : min %d  median %.0f  max %d"
          % (spans.min(), np.median(spans), spans.max()))
    print("  span ms     : min %.0f  median %.0f  max %.0f"
          % (spans.min() * 20, np.median(spans) * 20, spans.max() * 20))
    print("  -> TEMPLATE_FRAMES around %d covers the median take"
          % int(np.median(spans)))

    # ---- how loud is it --------------------------------------------------
    peaks = np.array(peaks)
    print()
    print("=" * 72)
    print("LEVELS -- peak frame RMS per take, in 24-bit units")
    print("=" * 72)
    print("  quietest take %8.0f" % peaks.min())
    print("  median   take %8.0f" % np.median(peaks))
    print("  loudest  take %8.0f" % peaks.max())
    print("  spread        %8.1f dB   <- a fixed SPEECH_FLOOR must live under this"
          % (20 * np.log10(peaks.max() / peaks.min())))
    print("  room floor    %8.0f  (median of the takes' quiet frames)"
          % np.median(floors))

    # ---- where is the energy --------------------------------------------
    speech = np.zeros(BANDS)
    quiet = np.zeros(BANDS)
    for _, f in takes:
        rms = frame_rms(f)
        floor = np.percentile(rms, 20)
        power = np.abs(np.fft.rfft(f * win, axis=1)) ** 2
        loud, still = rms > floor * 3.162, rms <= floor * 1.259
        for b in range(BANDS):
            sl = slice(edges[b], edges[b + 1])
            speech[b] += power[loud][:, sl].sum()
            quiet[b] += power[still][:, sl].sum()
    speech /= speech.sum()
    quiet /= quiet.sum()

    noise, noise_label = quiet, "quiet frames in these takes"
    if calib:
        with open(calib) as fh:
            spec = json.load(fh).get("spectrum")
        if spec:
            noise = np.array(spec["energy"], dtype=np.float64)
            noise /= noise.sum()
            noise_label = "Lab 3 noise spectrum (%s)" % os.path.basename(calib)

    print()
    print("=" * 72)
    print("SPECTRUM -- share of energy per band")
    print("noise reference: %s" % noise_label)
    print("=" * 72)
    print("band        Hz          speech%   noise%    speech/noise dB")
    for b in range(BANDS):
        print("  %2d   %5.0f-%5.0f     %6.2f   %6.2f        %+6.1f"
              % (b, hz[b], hz[b + 1], 100 * speech[b], 100 * noise[b],
                 10 * np.log10(speech[b] / noise[b])))

    print()
    print("Raising BAND_LO_HZ discards the low bands entirely:")
    print("  BAND_LO_HZ   speech kept   noise kept   SNR change")
    base = np.log10(speech.sum() / noise.sum())
    best = (0, -99)
    for k in range(6):
        s, n = speech[k:].sum(), noise[k:].sum()
        gain = 10 * (np.log10(s / n) - base)
        if gain > best[1]:
            best = (k, gain)
        print("     %5.0f       %6.1f%%      %6.1f%%      %+5.1f dB"
              % (hz[k], 100 * s, 100 * n, gain))
    print()
    print("  -> best SNR at BAND_LO_HZ = %.0f (%+.1f dB), keeping %.0f%% of speech"
          % (hz[best[0]], best[1], 100 * speech[best[0]:].sum()))
    print("     Judge this on speech kept as well as dB: a band that buys 1 dB")
    print("     while throwing away a third of the phrase is a bad trade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
