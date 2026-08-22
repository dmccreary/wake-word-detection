#!/usr/bin/env python3
"""Read the WAV takes from record-wake-words.py and say what they mean.

    python3 src/tools/analyze-wake-words.py docs/sounds/

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

BAND_LO_HZ defaults to whatever Lab 4 currently uses, so the bands printed here
are the bands the detector actually sees. Pass --lo=150 to widen the view back
down to where the furnace lives, which is how the current 350 was chosen.

Every number below is computed by `wakeword_analysis.py`, which the Wake Word
Explorer dashboard also imports. To see any of these tables as a picture:

    python3 src/tools/build-explorer-data.py
    mkdocs serve   # then open /dashboards/wake-word-explorer/

Runs on a host, not the Pico. Needs numpy.
"""

import json
import os
import sys

import numpy as np

import wakeword_analysis as wa

# These MUST match Lab 4, or the answer is about some other detector. They live
# in wakeword_analysis so the dashboard cannot disagree with this script.
N = wa.N
RATE = wa.RATE
BANDS = wa.BANDS
BAND_LO_HZ = wa.BAND_LO_HZ      # matches Lab 4; override with --lo=HZ
BAND_HI_HZ = wa.BAND_HI_HZ

RAMP = " .:-=+*#%@"


def main():
    global BAND_LO_HZ
    args = []
    for a in sys.argv[1:]:
        if a.startswith("--lo="):
            BAND_LO_HZ = float(a.split("=", 1)[1])
        else:
            args.append(a)
    folder = args[0] if args else "sounds"
    calib = args[1] if len(args) > 1 else None
    print("bands: %.0f-%.0f Hz in %d log-spaced steps\n"
          % (BAND_LO_HZ, BAND_HI_HZ, BANDS))

    names = sorted(f for f in os.listdir(folder) if f.endswith(".wav"))
    if not names:
        print("no .wav files in %s" % folder)
        return 1

    takes = [(n, wa.load(os.path.join(folder, n), warn=print)) for n in names]
    edges = wa.band_edges(BAND_LO_HZ, BAND_HI_HZ, BANDS)
    hz = wa.edges_hz(edges)

    # ---- envelopes -------------------------------------------------------
    print("=" * 72)
    print("ENVELOPE -- one character per %.0f ms frame, each take scaled to itself"
          % wa.FRAME_MS)
    print("=" * 72)
    for name, f in takes:
        rms = np.maximum(wa.frame_rms(f), 1e-9)
        db = 20 * np.log10(rms)
        lo, hi = np.percentile(db, wa.FLOOR_PERCENTILE), db.max()
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
    print("PHRASE EXTENT -- gate at noise floor + %.0f dB" % wa.LOUD_DB)
    print("=" * 72)
    print("take                  floor  peak frame   first  last  frames    ms")
    spans = []
    peaks = []
    floors = []
    for name, f in takes:
        rms = wa.frame_rms(f)
        floor, first, last = wa.phrase_extent(rms)
        if first is None:
            print("  %-20s  %5.0f  no frames above gate" % (name, floor))
            continue
        span = last - first + 1
        spans.append(span)
        peaks.append(rms.max())
        floors.append(floor)
        print("  %-20s  %5.0f  %10.0f   %5d %5d  %6d %5.0f"
              % (name, floor, rms.max(), first, last, span, span * wa.FRAME_MS))

    spans = np.array(spans)
    print()
    print("  span frames : min %d  median %.0f  max %d"
          % (spans.min(), np.median(spans), spans.max()))
    print("  span ms     : min %.0f  median %.0f  max %.0f"
          % (spans.min() * wa.FRAME_MS, np.median(spans) * wa.FRAME_MS,
             spans.max() * wa.FRAME_MS))
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
    speech, quiet = wa.spectrum_shares(takes, edges)

    noise, noise_label = quiet, "quiet frames in these takes"
    if calib:
        with open(calib) as fh:
            spec = json.load(fh).get("spectrum")
        # Lab 3 stores the band EDGES it measured against, and they are only
        # comparable band-for-band if they are the same edges we just used.
        # Silently lining up two different frequency layouts would produce a
        # table that looks authoritative and compares 350-400 Hz of speech
        # against 150-200 Hz of noise.
        # Compared with a one-bin tolerance, not for equality. The edges are
        # built by int(lo * ratio ** b), and ratio ** BANDS lands a hair under
        # its exact value on MicroPython's floats but exactly on it here -- so
        # the board reports a top edge of 5950 Hz where this host computes
        # 6000. One bin, and not worth rejecting a valid reference over.
        tol = wa.BIN_HZ           # one FFT bin, 50 Hz
        same = (spec and len(spec["edges_hz"]) == len(hz) and
                all(abs(a - b) <= tol for a, b in zip(spec["edges_hz"], hz)))
        if same:
            noise = np.array(spec["energy"], dtype=np.float64)
            noise /= noise.sum()
            noise_label = "Lab 3 noise spectrum (%s)" % os.path.basename(calib)
        elif spec:
            print("note: %s was measured on %.0f-%.0f Hz bands, not the %.0f-%.0f"
                  % (os.path.basename(calib), spec["edges_hz"][0],
                     spec["edges_hz"][-1], hz[0], hz[-1]))
            print("      used here, so its spectrum cannot be lined up band for")
            print("      band. Falling back to the quiet frames in these takes.")
            print("      Re-run with --lo=%.0f to use it." % spec["edges_hz"][0])

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
    rows = wa.sweep(speech, noise, hz)
    best = max(rows, key=lambda r: r[3])
    for cut, s, n, gain in rows:
        print("     %5.0f       %6.1f%%      %6.1f%%      %+5.1f dB"
              % (cut, 100 * s, 100 * n, gain))
    print()
    print("  -> best SNR at BAND_LO_HZ = %.0f (%+.1f dB), keeping %.0f%% of speech"
          % (best[0], best[3], 100 * best[1]))
    print("     Judge this on speech kept as well as dB: a band that buys 1 dB")
    print("     while throwing away a third of the phrase is a bad trade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
