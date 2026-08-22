#!/usr/bin/env python3
"""Check that the Wake Word Explorer is plotting what the analyzer prints.

    python3 src/tools/test_explorer_data.py

The dashboard's whole claim is that its pictures and the command-line tables
come from the same measurements. That claim is only true for as long as nobody
edits one side of it, so this checks it rather than asserting it.

Three things, in order of how badly they would mislead a student if wrong:

  1. The quantized spectrogram in takes.json still reproduces the band energies
     numpy computes from the raw WAVs. This is the one that matters -- the
     browser does all its band arithmetic on that array, so if quantization
     ever cost real precision, every plotted level would be off and nothing
     would look wrong.

  2. The per-cutoff tables the dashboard DISPLAYS match a direct computation.
     These are the numbers a student writes down.

  3. The per-take figures -- floor, peak, phrase extent -- match
     analyze-wake-words.py's PHRASE EXTENT table row for row.

Run it after changing wakeword_analysis.py, build-explorer-data.py, or the
takes in docs/sounds/. It needs takes.json to exist, so build first.
"""

import json
import os
import sys

import numpy as np

import wakeword_analysis as wa

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "docs", "dashboards", "wake-word-explorer",
                    "data", "takes.json")

fails = []


def check(label, got, want, tol):
    ok = abs(got - want) <= tol
    if not ok:
        fails.append("%s: got %.6g, want %.6g (tol %.3g)" % (label, got, want, tol))
    return ok


def decode_spectrogram(take, const):
    """Undo exactly what the browser undoes, so this tests the same array."""
    import base64
    q = np.frombuffer(base64.b64decode(take["spec_b64"]), dtype="<u2")
    db = const["DB_OFFSET"] + q.astype(np.float64) * const["DB_STEP"]
    return (10 ** (db / 10)).reshape(take["spec_shape"])


def main():
    if not os.path.exists(DATA):
        print("no %s -- run build-explorer-data.py first"
              % os.path.relpath(DATA, ROOT))
        return 1

    with open(DATA) as fh:
        doc = json.load(fh)
    const = doc["constants"]
    folder = os.path.join(ROOT, doc["source_folder"])

    print("checking %d takes from %s against %s"
          % (len(doc["takes"]), doc["source_folder"],
             os.path.relpath(DATA, ROOT)))
    print()

    # ---- 1. the shipped spectrogram vs numpy ----------------------------
    print("1. quantized spectrogram reproduces numpy's band energies")
    worst_db = 0.0
    speech_bins = np.zeros(wa.N // 2 + 1)
    noise_bins = np.zeros(wa.N // 2 + 1)

    for t in doc["takes"]:
        frames = wa.load(os.path.join(folder, t["name"]))
        power = wa.power_spectrogram(frames)
        shipped = decode_spectrogram(t, const)

        if shipped.shape != power.shape:
            fails.append("%s: shape %s vs %s" % (t["name"], shipped.shape, power.shape))
            continue

        rms = wa.frame_rms(frames)
        loud, still = wa.frame_classes(rms)
        speech_bins += power[loud].sum(axis=0)
        noise_bins += power[still].sum(axis=0)

        for cutoff in doc["cutoffs"]:
            edges = cutoff["edges"]
            a = wa.band_rms(power, edges)
            b = wa.band_rms(shipped, edges)
            d = float(np.abs(20 * np.log10(a / b)).max())
            worst_db = max(worst_db, d)
            # The browser's own console check uses 0.02 dB. Anything close to
            # that from quantization alone would mean DB_STEP is too coarse.
            if d > 0.005:
                fails.append("%s @%d Hz: band RMS differs by %.4f dB"
                             % (t["name"], cutoff["hz"], d))

            # And the checksum the browser is handed must be right, or the
            # browser is checking itself against a wrong answer.
            want = t["checks"][str(cutoff["hz"])]
            check("%s @%d Hz shipped band-RMS checksum" % (t["name"], cutoff["hz"]),
                  float(20 * np.log10(a.mean())), want[0], 1e-3)
            check("%s @%d Hz shipped feature checksum" % (t["name"], cutoff["hz"]),
                  float(np.abs(wa.feature_vectors(power, edges)).mean()), want[1], 1e-5)

    print("   worst band-RMS error across every take and cutoff: %.5f dB" % worst_db)

    # ---- 2. the tables the dashboard displays ---------------------------
    print("2. per-cutoff tables match a direct computation")
    ref_lo = wa.band_edges(const["REFERENCE_CUTOFF_HZ"])[0]
    ref_hi = wa.band_edges(const["REFERENCE_CUTOFF_HZ"])[-1]
    ref_s = speech_bins[ref_lo:ref_hi].sum()
    ref_n = noise_bins[ref_lo:ref_hi].sum()
    base = np.log10(ref_s / ref_n)

    for cutoff in doc["cutoffs"]:
        edges = wa.band_edges(cutoff["hz"])
        if edges != cutoff["edges"]:
            fails.append("%d Hz: shipped edges %s vs computed %s"
                         % (cutoff["hz"], cutoff["edges"], edges))
            continue
        s = speech_bins[edges[0]:edges[-1]].sum()
        n = noise_bins[edges[0]:edges[-1]].sum()
        check("%d Hz speech_kept" % cutoff["hz"],
              cutoff["speech_kept"], float(s / ref_s), 1e-5)
        check("%d Hz noise_kept" % cutoff["hz"],
              cutoff["noise_kept"], float(n / ref_n), 1e-5)
        check("%d Hz snr_change_db" % cutoff["hz"], cutoff["snr_change_db"],
              float(10 * (np.log10(s / n) - base)), 2e-3)

        sb = np.array([speech_bins[edges[b]:edges[b + 1]].sum()
                       for b in range(wa.BANDS)])
        sb = sb / sb.sum()
        for b in range(wa.BANDS):
            check("%d Hz band %d speech share" % (cutoff["hz"], b),
                  cutoff["speech_share"][b], float(sb[b]), 1e-5)

    # ---- 3. the per-take figures ----------------------------------------
    print("3. per-take figures match the PHRASE EXTENT table")
    for t in doc["takes"]:
        frames = wa.load(os.path.join(folder, t["name"]))
        rms = wa.frame_rms(frames)
        floor, first, last = wa.phrase_extent(rms)
        check("%s floor" % t["name"], t["floor_rms"], floor, 0.01)
        check("%s peak" % t["name"], t["peak_rms"], float(rms.max()), 0.01)
        if (t["first_frame"], t["last_frame"]) != (first, last):
            fails.append("%s: phrase %s-%s vs %s-%s"
                         % (t["name"], t["first_frame"], t["last_frame"], first, last))

    print()
    if fails:
        print("FAILED (%d)" % len(fails))
        for f in fails[:20]:
            print("  " + f)
        if len(fails) > 20:
            print("  ... and %d more" % (len(fails) - 20))
        return 1
    print("PASS -- the dashboard is plotting what the analyzer prints.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
