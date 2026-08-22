#!/usr/bin/env python3
"""Turn a folder of wake-word takes into the data file the dashboard plots.

    python3 src/tools/build-explorer-data.py
    python3 src/tools/build-explorer-data.py path/to/sounds

Writes docs/dashboards/wake-word-explorer/data/takes.json, which points back at
the WAVs in docs/sounds/ rather than copying them -- one set of takes, served
straight out of the site root where the browser can reach them.

Every number in here comes from `wakeword_analysis.py`, the same module
`analyze-wake-words.py` prints its tables from. That is the whole design of
this file: the dashboard exists so a student can check a printed claim against
a picture, and a picture drawn from a second, private copy of the band math
could only ever confirm itself.

What ships, and why each piece is shaped the way it is:

  * A power spectrogram per take -- |X(k)|^2 for all 129 bins of every 20 ms
    frame, quantized to 0.005 dB. The browser sums subsets of those bins to
    follow the BAND_LO_HZ slider, which is addition rather than signal
    processing, so nothing about the analysis is re-implemented in JavaScript.
    Shipping the finished per-cutoff curves instead would be four times larger
    and would still need this array for the spectrogram plot.

  * A min/max decimated waveform, from the int16 samples as recorded. The
    browser multiplies by GAIN to reach the 24-bit units everything else uses.

  * Reference tables computed HERE for every cutoff the slider can reach.
    Anything the dashboard displays as a number -- band shares, SNR, the
    sweep -- is read from these rather than recomputed, so a printed table and
    the panel beside it cannot disagree.

  * A per-(take, cutoff) checksum of the band-limited RMS and of the feature
    vectors. The browser recomputes both from the spectrogram and complains in
    the console if either has drifted. Cheap insurance that the summing above
    still lands where numpy did.

Runs on a host, not the Pico. Needs numpy.
"""

import base64
import json
import os
import sys

import numpy as np

import wakeword_analysis as wa

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# The takes live under docs/ so that `mkdocs serve` can hand them to the
# browser for playback -- the dashboard fetches and filters the real audio, and
# a web server can only serve what is inside the site root. record-wake-words.py
# writes them to a `sounds/` folder on the Pico; copy that folder here.
DEFAULT_SOUNDS = os.path.join(ROOT, "docs", "sounds")
DEFAULT_CALIB = os.path.join(ROOT, "src", "labs", "results", "calibration.json")
DASHBOARD = os.path.join(ROOT, "docs", "dashboards", "wake-word-explorer")

# Every cutoff the BAND_LO_HZ slider can stop on. All multiples of BIN_HZ,
# because 50 Hz is the finest distinction a 256-point FFT at 12.8 kHz can
# actually make -- a slider offering 373 Hz would be inventing precision.
CUTOFFS_HZ = [100, 150, 200, 250, 300, 350, 400, 450,
              500, 550, 600, 650, 700, 800, 900, 1000]

# The cutoff every other one is scored against, and the one Lab 4 shipped with
# before the takes were analyzed. "+9.0 dB at 350 Hz" is meaningless without
# saying "compared to what".
REFERENCE_CUTOFF_HZ = 150

# Display-only compression of the waveform. 32 samples is 2.5 ms per column,
# giving 1200 columns for a 3 second take -- more than a full-width plot has
# pixels, and 1/16th the bytes of shipping every sample.
WAVE_DECIM = 32

# Quantization of the spectrogram. 0.005 dB steps from -60 dB, which puts the
# worst-case band-sum error four decimal places below anything displayed.
DB_OFFSET = -60.0
DB_STEP = 0.005
DB_MAX = DB_OFFSET + DB_STEP * 65535


def b64(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii")


def wave_minmax(path):
    """Min/max pairs of the raw int16 samples, one pair per WAVE_DECIM samples.

    Read from the file rather than from wa.load()'s framed float array so the
    numbers stay exactly the integers the Pico wrote. The browser applies GAIN
    to reach 24-bit units, which is the one scalar it is trusted with.
    """
    import wave as wavemod
    with wavemod.open(path, "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    keep = len(x) // WAVE_DECIM * WAVE_DECIM
    cols = x[:keep].reshape(-1, WAVE_DECIM)
    return cols.min(axis=1).astype("<i2"), cols.max(axis=1).astype("<i2")


def quantize_db(power):
    """Power spectrogram as uint16 decibels."""
    db = 10 * np.log10(np.maximum(power, 1e-12))
    db = np.clip(db, DB_OFFSET, DB_MAX)
    return np.round((db - DB_OFFSET) / DB_STEP).astype("<u2")


def cutoff_bin(hz):
    """The first FFT bin at or above `hz`, matching band_edges()'s `lo`."""
    return max(1, int(hz / wa.BIN_HZ))


def build_cutoff_tables(speech_bins, noise_bins, lab3=None):
    """Per-cutoff band tables and the SNR sweep, from bin-resolved energy.

    `speech_bins` and `noise_bins` are total power per FFT bin, pooled over
    every take -- speech from the frames above each take's gate, noise from the
    frames sitting on its floor.

    `lab3` is Lab 3's measured furnace spectrum, if there is one. It is BAND-
    resolved rather than bin-resolved, so it can only answer for cutoffs that
    land on one of its own band edges; the rest get None and the dashboard
    greys the choice out. This is the same restriction analyze-wake-words.py
    prints a note about, for the same reason: lining up two different frequency
    layouts produces a table that looks authoritative while comparing one
    band of speech against a different band of noise.
    """
    ref_lo = cutoff_bin(REFERENCE_CUTOFF_HZ)
    ref_hi = wa.band_edges(REFERENCE_CUTOFF_HZ)[-1]
    ref_s = speech_bins[ref_lo:ref_hi].sum()
    ref_n = noise_bins[ref_lo:ref_hi].sum()
    base = np.log10(ref_s / ref_n)

    l3_hz = l3_energy = None
    if lab3 and lab3.get("spectrum_edges_hz"):
        l3_hz = lab3["spectrum_edges_hz"]
        l3_energy = np.array(lab3["spectrum_energy"], dtype=np.float64)
        l3_base = np.log10(ref_s / l3_energy.sum())

    out = []
    for hz in CUTOFFS_HZ:
        edges = wa.band_edges(hz)
        lo, hi = edges[0], edges[-1]
        s, n = speech_bins[lo:hi].sum(), noise_bins[lo:hi].sum()

        # Shares WITHIN this cutoff's own bands, which is what the printed
        # SPECTRUM table shows: how the phrase distributes itself across the
        # twelve bands the detector would actually be looking at.
        sb = np.array([speech_bins[edges[b]:edges[b + 1]].sum()
                       for b in range(wa.BANDS)])
        nb = np.array([noise_bins[edges[b]:edges[b + 1]].sum()
                       for b in range(wa.BANDS)])
        row = {
            "hz": hz,
            "lo_bin": lo,
            "edges": edges,
            "edges_hz": [round(e, 1) for e in wa.edges_hz(edges)],
            "speech_share": [round(float(v), 6) for v in sb / sb.sum()],
            "noise_share": [round(float(v), 6) for v in nb / nb.sum()],
            "snr_db": [round(float(v), 3)
                       for v in 10 * np.log10((sb / sb.sum()) / (nb / nb.sum()))],
            # The sweep, relative to REFERENCE_CUTOFF_HZ: what this cutoff
            # keeps of the phrase, what it keeps of the room, and the net.
            "speech_kept": round(float(s / ref_s), 6),
            "noise_kept": round(float(n / ref_n), 6),
            "snr_change_db": round(float(10 * (np.log10(s / n) - base)), 3),
            "lab3_noise_kept": None,
            "lab3_snr_change_db": None,
        }

        # Lab 3's answer to the same question, where its edges permit one.
        if l3_hz is not None:
            k = next((i for i, e in enumerate(l3_hz)
                      if abs(e - hz) <= wa.BIN_HZ / 2 and i < len(l3_energy)), None)
            if k is not None:
                l3_n = l3_energy[k:].sum()
                row["lab3_noise_kept"] = round(float(l3_n / l3_energy.sum()), 6)
                row["lab3_snr_change_db"] = round(
                    float(10 * (np.log10(s / l3_n) - l3_base)), 3)
        out.append(row)
    return out


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOUNDS
    calib_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CALIB

    names = sorted(f for f in os.listdir(folder) if f.endswith(".wav"))
    if not names:
        print("no .wav files in %s" % folder)
        return 1

    data_out = os.path.join(DASHBOARD, "data")
    os.makedirs(data_out, exist_ok=True)

    n_bins = wa.N // 2 + 1
    speech_bins = np.zeros(n_bins)
    noise_bins = np.zeros(n_bins)
    takes = []

    for name in names:
        path = os.path.join(folder, name)
        frames = wa.load(path, warn=print)
        rms = wa.frame_rms(frames)
        power = wa.power_spectrogram(frames)
        floor, first, last = wa.phrase_extent(rms)
        loud, still = wa.frame_classes(rms)

        speech_bins += power[loud].sum(axis=0)
        noise_bins += power[still].sum(axis=0)

        lo16, hi16 = wave_minmax(path)
        q = quantize_db(power)

        # The reference the browser has to reproduce: mean band-limited RMS in
        # dB, at every cutoff, computed here by numpy from unquantized power.
        checks = {}
        for hz in CUTOFFS_HZ:
            edges = wa.band_edges(hz)
            br = wa.band_rms(power, edges)
            fv = wa.feature_vectors(power, edges)
            checks[str(hz)] = [round(float(20 * np.log10(br.mean())), 4),
                               round(float(np.abs(fv).mean()), 6)]

        takes.append({
            "name": name,
            "label": os.path.splitext(name)[0].rsplit("-", 1)[-1],
            "wav": os.path.relpath(path, DASHBOARD).replace(os.sep, "/"),
            "n_frames": int(frames.shape[0]),
            "seconds": round(frames.size / wa.RATE, 4),
            "floor_rms": round(floor, 2),
            "peak_rms": round(float(rms.max()), 2),
            "first_frame": first,
            "last_frame": last,
            "span_frames": None if first is None else last - first + 1,
            "loud_frames": int(loud.sum()),
            "quiet_frames": int(still.sum()),
            "rms": [round(float(v), 2) for v in rms],
            "wave_min_b64": b64(lo16),
            "wave_max_b64": b64(hi16),
            "spec_b64": b64(q),
            "spec_shape": [int(q.shape[0]), int(q.shape[1])],
            "checks": checks,   # [mean band RMS in dB, mean |feature|]
        })
        print("  %-20s %3d frames  floor %6.0f  peak %8.0f  %s"
              % (name, frames.shape[0], floor, rms.max(),
                 "no gate crossing" if first is None
                 else "phrase %d-%d" % (first, last)))

    # Lab 3's furnace spectrum, kept only when its band edges line up with ours
    # to within a bin. Two different frequency layouts plotted on one axis is a
    # chart that looks authoritative while comparing 350-400 Hz of speech
    # against 150-200 Hz of noise -- see the same check in
    # analyze-wake-words.py for why the tolerance is one bin and not zero.
    calibration = None
    if os.path.exists(calib_path):
        with open(calib_path) as fh:
            cal = json.load(fh)
        spec = cal.get("spectrum")
        ref_hz = wa.edges_hz(wa.band_edges(REFERENCE_CUTOFF_HZ))
        aligned = bool(spec and len(spec["edges_hz"]) == len(ref_hz) and
                       all(abs(a - b) <= wa.BIN_HZ
                           for a, b in zip(spec["edges_hz"], ref_hz)))
        calibration = {
            "file": os.path.basename(calib_path),
            "room_note": cal.get("room_note"),
            "noise_median": cal.get("noise", {}).get("median"),
            "noise_median_spl": cal.get("noise", {}).get("median_spl"),
            "noise_p99": cal.get("noise", {}).get("percentiles", {}).get("p99"),
            "speech_top_decile": cal.get("speech", {}).get("top_decile"),
            "speech_floor": cal.get("recommended", {}).get("speech_floor"),
            "speech_floor_fraction":
                cal.get("recommended", {}).get("speech_floor_fraction"),
            "set_by": cal.get("recommended", {}).get("set_by"),
            "snr_db": cal.get("recommended", {}).get("snr_db"),
            "spectrum_edges_hz": spec.get("edges_hz") if spec else None,
            "spectrum_energy": spec.get("energy") if spec else None,
            "spectrum_aligned_at_hz": REFERENCE_CUTOFF_HZ if aligned else None,
        }

    cutoffs = build_cutoff_tables(speech_bins, noise_bins, calibration)

    doc = {
        "source_folder": os.path.relpath(folder, ROOT),
        "constants": {
            "N": wa.N,
            "RATE": wa.RATE,
            "BANDS": wa.BANDS,
            "BAND_LO_HZ": wa.BAND_LO_HZ,
            "BAND_HI_HZ": wa.BAND_HI_HZ,
            "BIN_HZ": wa.BIN_HZ,
            "FRAME_MS": wa.FRAME_MS,
            "GAIN": wa.GAIN,
            "FULL_SCALE": wa.FULL_SCALE,
            "SPL_OFFSET": wa.SPL_OFFSET,
            "BAND_RMS_SCALE": wa.BAND_RMS_SCALE,
            "WINDOW_POWER": wa.WINDOW_POWER,
            "FLOOR_PERCENTILE": wa.FLOOR_PERCENTILE,
            "LOUD_DB": wa.LOUD_DB,
            "QUIET_DB": wa.QUIET_DB,
            "SPEECH_FLOOR": wa.FULL_SCALE * 0.00530,
            "WAVE_DECIM": WAVE_DECIM,
            "DB_OFFSET": DB_OFFSET,
            "DB_STEP": DB_STEP,
            "REFERENCE_CUTOFF_HZ": REFERENCE_CUTOFF_HZ,
        },
        "cutoffs": cutoffs,
        "takes": takes,
        "calibration": calibration,
    }

    out_path = os.path.join(data_out, "takes.json")
    with open(out_path, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))

    kb = os.path.getsize(out_path) / 1024.0
    print()
    print("wrote %s (%.0f KB)" % (os.path.relpath(out_path, ROOT), kb))
    print("%d takes, played from %s" % (len(names), os.path.relpath(folder, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
