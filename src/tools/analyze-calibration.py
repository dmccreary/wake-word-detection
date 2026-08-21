#!/usr/bin/env python3
"""Read a calibration.json from Lab 3 and say what it means.

    python3 src/tools/analyze-calibration.py src/labs/results/calibration.json

Lab 3 prints its numbers as it measures them. This reads the saved file
afterward and answers the questions the console cannot, because they need the
whole distribution at once:

  * Is a workable SPEECH_FLOOR even available in this room?
  * Are the loud "quiet room" frames periodic or occasional? Periodic points at
    something on the board firing on a schedule; occasional points at the room.
  * Does the noise sit low enough in frequency that raising BAND_LO_HZ in Lab 4
    would buy more than any threshold tuning?

Runs on a host, not the Pico. Nothing here touches hardware.
"""

import json
import math
import sys


def db(x):
    """Level ratio in dB. Not dBFS -- this is used for comparing two levels."""
    return 20.0 * math.log10(x) if x > 0 else float("-inf")


def dbfs(rms, full_scale):
    return db(rms / full_scale) if rms > 0 else -120.0


def rule(title):
    print()
    print(title)
    print("-" * len(title))


def analyze_noise(noise, full_scale, spl_offset):
    """The distribution shape, and what it implies about the loud frames."""
    rule("ROOM NOISE")
    pct = noise.get("percentiles") or {}
    med = noise["median"]
    print("  median  %8.0f   %6.1f dBFS   ~%.0f dB SPL"
          % (med, dbfs(med, full_scale), dbfs(med, full_scale) + spl_offset))
    print("  worst   %8.0f   %6.1f dBFS   ~%.0f dB SPL"
          % (noise["max"], dbfs(noise["max"], full_scale),
             dbfs(noise["max"], full_scale) + spl_offset))

    if not pct:
        print("  (no percentile block -- measured by an older version of Lab 3)")
        return None

    print()
    print("  distribution over %d frames:" % pct.get("frames", 0))
    ref = pct["p50"]
    for key in ("p10", "p25", "p50", "p75", "p90", "p99", "max"):
        if key not in pct:
            continue
        v = pct[key]
        bar = "#" * int(max(0, min(40, (db(v / ref) + 2) * 3)))
        print("    %-4s %8.0f  %+6.1f dB vs median  %s" % (key, v, db(v / ref), bar))

    # A display that redraws every 8th frame contaminates ~12.5% of frames --
    # a second population sitting on top of a quiet one, not a long tail. That
    # shows up as a STEP between p75 and p90 with little spread above it.
    # Genuine acoustic transients do the opposite: a smooth body with a few
    # isolated spikes at the very top.
    step_db = db(pct["p90"] / pct["p75"])
    tail_db = db(pct["max"] / pct["p90"])
    print()
    print("  p75 -> p90 step : %+5.1f dB" % step_db)
    print("  p90 -> max tail : %+5.1f dB" % tail_db)
    print()
    if step_db >= 3.0 and step_db > tail_db:
        print("  VERDICT: looks PERIODIC. Roughly the top tenth of frames sit in a")
        print("  band of their own rather than trailing off, which is the shape you")
        print("  get when something fires on a schedule -- Lab 3 pushes the OLED")
        print("  over SPI every 8th frame (12.5%), and the mic sits directly above")
        print("  that display. Test it: raise the redraw interval in collect() from")
        print("  8 to 64 and re-measure. If the step shrinks, it was the display.")
        return "periodic"
    if tail_db >= 3.0 and tail_db > step_db:
        print("  VERDICT: looks like ACOUSTIC TRANSIENTS. The body of the")
        print("  distribution is tight and only a few frames at the very top run")
        print("  away, which is a room event (a door, a compressor kicking in),")
        print("  not something on the board keeping time.")
        return "transient"
    print("  VERDICT: no strong signal either way. The loud frames are neither a")
    print("  clean second population nor isolated spikes.")
    return "unclear"


def analyze_spectrum(spec, bin_hz):
    rule("NOISE SPECTRUM")
    edges, energy = spec["edges_hz"], spec["energy"]
    # Lab 3 stores MEAN power per bin. Total power in a band needs the bin
    # count too, and these bands are log-spaced -- the top band spans 31 bins
    # against the bottom band's 1. Summing the means directly overstates the
    # low end badly (89% vs the true 76%, on the first data this was run on).
    bins = [int(round(h / bin_hz)) for h in edges]
    counts = [max(1, bins[i + 1] - bins[i]) for i in range(len(energy))]
    power = [energy[i] * counts[i] for i in range(len(energy))]
    peak = max(energy) or 1.0
    for b, e in enumerate(energy):
        rel = 10 * math.log10(e / peak + 1e-12)
        print("  %5d-%5d Hz  %6.1f dB  %s"
              % (edges[b], edges[b + 1], rel, "#" * int(max(0, (rel + 40) / 2))))
    worst = energy.index(peak)
    print()
    print("  loudest band: %d-%d Hz" % (edges[worst], edges[worst + 1]))
    # Energy below ~400 Hz is fan and HVAC rumble. It is cheap to discard,
    # because almost nothing that distinguishes one spoken phrase from another
    # lives down there.
    total = sum(power) or 1.0
    print()
    print("  share of total noise power (bin-count weighted):")
    for cut in (250, 400, 500):
        low = sum(power[b] for b in range(len(power)) if edges[b + 1] <= cut)
        f = low / total
        # Removing a fraction f of the POWER leaves sqrt(1-f) of the
        # amplitude, so the RMS drop in dB is -10*log10(1-f) already.
        drop = -10 * math.log10(max(1e-9, 1 - f))
        print("    below %4d Hz: %2.0f%%  -- discarding it lowers noise RMS %.1f dB"
              % (cut, f * 100, drop))
    low = sum(power[b] for b in range(len(power)) if edges[b + 1] <= 400)
    frac = low / total
    if frac > 0.30:
        print()
        print("  A third or more of the noise is low-frequency rumble -- consistent")
        print("  with a furnace fan. Raising BAND_LO_HZ in Lab 4 above %d Hz throws"
              % edges[min(worst + 1, len(edges) - 1)])
        print("  most of it away and costs almost no speech information.")


def analyze_gate(d, full_scale, spl_offset):
    rule("SPEECH_FLOOR")
    noise, speech, rec = d.get("noise"), d.get("speech"), d.get("recommended")
    if not rec or not speech:
        print("  No recommendation in this file -- NOISE and SPEECH are both")
        print("  required. Run the SPEECH measurement and fetch the file again.")
        return
    snr = rec["snr_db"]
    print("  recommended : FULL_SCALE * %.5f  (%.1f dBFS)"
          % (rec["speech_floor_fraction"], rec["speech_floor_dbfs"]))
    print("  currently   : FULL_SCALE * %.5f"
          % d["config"]["speech_floor_in_config"])
    print("  set by rule : %s" % rec.get("set_by"))
    print("  SNR         : %.1f dB (speech top-decile vs median noise)" % snr)
    print()

    cur = d["config"]["speech_floor_in_config"] * full_scale
    if cur < noise["median"]:
        print("  !! The gate in config.py sits BELOW the median of an empty room.")
        print("     More than half of silent frames pass it, so the detector")
        print("     scores room noise continuously. This must change.")
    elif cur < noise["max"]:
        print("  !  The gate in config.py sits below the WORST noise frame, so the")
        print("     loudest quiet-room moments still get through.")

    if rec.get("set_by") == "capped-at-0.7x-speech":
        print()
        print("  The 4x-worst-noise rule wanted a gate louder than 70% of your own")
        print("  voice, so it was capped. That means no clean separation exists in")
        print("  this room: the recommended value is a compromise that will let")
        print("  some noise through. The fix is physical, not numerical --")
        print("  halving the distance to the mic buys ~6 dB, and 15 in -> 7.5 in")
        print("  would do it.")
    if snr < 15:
        print()
        print("  SNR under 15 dB is a hard room. Expect false rejects no matter")
        print("  what threshold Lab 4 uses.")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    with open(sys.argv[1]) as f:
        d = json.load(f)

    cfg = d["config"]
    full_scale, spl_offset = cfg["full_scale"], cfg["spl_offset"]

    print("=" * 62)
    print("Lab 3 calibration -- %s" % sys.argv[1])
    print("=" * 62)
    print("produced by: %s v%s  (config v%s, schema %s)"
          % (d.get("program", "?"), d.get("version", "?"),
             d.get("config_version", "?"), d.get("schema", "?")))
    print("room: %s" % (d.get("room_note") or "(unset)"))
    t = d.get("timing")
    if t:
        ok = abs(t["elapsed_ms"] - t["expected_ms"]) <= t["expected_ms"] * 0.2
        print("last measurement: %d ms of an expected %d ms, %d-%d samples/frame  %s"
              % (t["elapsed_ms"], t["expected_ms"],
                 t["samples_per_frame_min"], t["samples_per_frame_max"],
                 "OK" if ok else "<-- SHORT, levels are untrustworthy"))
    print("%d Hz, %d-sample frames, %d bands %d-%d Hz, %s FFT"
          % (cfg["sample_rate"], cfg["fft_n"], cfg["bands"],
             cfg["band_lo_hz"], cfg["band_hi_hz"],
             "assembly" if cfg.get("asm_fft") else "Python"))

    if d.get("noise"):
        analyze_noise(d["noise"], full_scale, spl_offset)
    else:
        rule("ROOM NOISE")
        print("  not measured")

    if d.get("speech"):
        rule("SPEECH")
        sp = d["speech"]
        print("  top decile %8.0f   %6.1f dBFS   ~%.0f dB SPL"
              % (sp["top_decile"], sp["top_decile_dbfs"],
                 sp["top_decile_dbfs"] + spl_offset))
        print("  peak       %8.0f   %6.1f dBFS" % (sp["peak"], sp["peak_dbfs"]))

    if d.get("clip"):
        rule("HEADROOM")
        pct = d["clip"]["percent_of_full_scale"]
        print("  loudest sample: %.1f%% of full scale" % pct)
        if pct > 90:
            print("  CLIPPING -- the mic is being overloaded.")
        elif pct < 5:
            print("  Very quiet. Nothing is wrong, but there is a lot of unused")
            print("  range; the mic could sit closer.")

    if d.get("spectrum"):
        analyze_spectrum(d["spectrum"], cfg["sample_rate"] / cfg["fft_n"])

    analyze_gate(d, full_scale, spl_offset)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
