"""The measurement math behind the wake-word takes, in one place.

Nothing here prints anything or draws anything. It exists so that
`analyze-wake-words.py` (which prints tables) and `build-explorer-data.py`
(which feeds the Wake Word Explorer dashboard) compute their numbers from the
same lines of code rather than from two copies that agree until one of them is
edited.

That is not a hypothetical worry. The whole point of the dashboard is to let a
student check a printed claim against a picture. A picture drawn from its own
private copy of the band math can only ever confirm itself.

The constants below MUST match Lab 4, or every answer is about some other
detector. They are duplicated from `src/labs/04-wake-word-test.py` rather than
imported because that file is MicroPython and expects `machine`, `ssd1306` and
a Pico attached to the other end of it.

Runs on a host, not the Pico. Needs numpy.
"""

import wave

import numpy as np

# ---------------------------------------------------------------------------
# Lab 4's parameters
# ---------------------------------------------------------------------------

N = 256                 # samples per frame
RATE = 12800            # Hz
BANDS = 12              # feature bands per frame
BAND_LO_HZ = 350        # Lab 4's measured band floor
BAND_HI_HZ = 6000

BIN_HZ = RATE / N       # 50 Hz -- the finest cutoff this analysis can resolve
FRAME_MS = N / RATE * 1000.0

# record-wake-words.py amplifies on the way to 16 bits so the files are not all
# crammed into the bottom of their range. Undoing it here puts every level back
# into the 24-bit units that calibration.json and Lab 4's console both use.
#
# The recorder writes `w >> (16 - GAIN_SHIFT)` where `w` is the microphone's
# 32-bit word, and the 24-bit sample everything else quotes is `w >> 8`. So the
# file holds `sample24 >> (8 - GAIN_SHIFT)` and getting back needs a factor of
# 64, not the 4 that GAIN_SHIFT multiplies by. Those are two different numbers:
# 4 is the gain relative to a straight 24-to-16 bit conversion, and that
# conversion has already divided by 256.
#
# Cross-checked rather than merely derived, because a factor this quiet is
# exactly the kind that survives inspection. The quiet frames of these takes
# put the room at 6,879 in 24-bit units; Lab 3 measured the same room at 7,221
# (calibration.json, noise median). 0.4 dB apart at 64, and 24.5 dB apart at 4.
RECORDER_GAIN_SHIFT = 2                 # record-wake-words.py's GAIN_SHIFT
GAIN = 1 << (8 - RECORDER_GAIN_SHIFT)   # 64

FULL_SCALE = 8388608                    # 2^23, config.FULL_SCALE
SPL_OFFSET = 94.0 - (-26.0)             # config.SPL_OFFSET: dBFS + this = dB SPL

# The gate that decides which frames are "speech" and which are "room", set
# relative to each take's own floor rather than at a fixed level. A fixed gate
# is exactly the mistake that made Lab 4's fill percentage meaningless: set it
# below the room and silence reads as speech, set it near the peak and only the
# loudest vowel survives.
FLOOR_PERCENTILE = 20                   # "quiet" = this percentile of frame RMS
LOUD_DB = 10.0                          # speech is this far above the floor
QUIET_DB = 2.0                          # room is within this much of it

LOUD_RATIO = 10 ** (LOUD_DB / 20)       # 3.162
QUIET_RATIO = 10 ** (QUIET_DB / 20)     # 1.259


def hann(n=N):
    """The same window Lab 4 builds, to the same formula."""
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / (n - 1))


WINDOW = hann()

# Turns a sum of band powers back into an RMS in the SAME 24-bit units the old
# time-domain gate used. Lab 4 derives this identically; the comment there
# explains each of the three factors. Keeping the formula rather than the
# number means a change to the window cannot silently invalidate it.
WINDOW_POWER = float((WINDOW * WINDOW).mean())
BAND_RMS_SCALE = 2.0 / (N * N * WINDOW_POWER)


def band_edges(lo_hz=BAND_LO_HZ, hi_hz=BAND_HI_HZ, bands=BANDS):
    """Lab 4's log-spaced band edges, in FFT bin numbers.

    Recomputed exactly as the lab does it, integer truncation and all, so the
    bands drawn on screen are the bands the detector actually sums.
    """
    lo = max(1, int(lo_hz / BIN_HZ))
    hi = min(N // 2 - 1, int(hi_hz / BIN_HZ))
    ratio = (hi / lo) ** (1.0 / bands)
    edges = [int(lo * ratio ** b) for b in range(bands + 1)]
    for b in range(bands):
        if edges[b + 1] <= edges[b]:
            edges[b + 1] = edges[b] + 1
    return edges


def edges_hz(edges):
    """Bin-number edges as frequencies."""
    return [e * BIN_HZ for e in edges]


def load(path, warn=None):
    """One take, as float samples in 24-bit units, framed like the detector."""
    with wave.open(path, "rb") as w:
        if w.getframerate() != RATE and warn is not None:
            warn("  warning: %s is %d Hz, expected %d"
                 % (path, w.getframerate(), RATE))
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    x = x.astype(np.float64) * GAIN
    return x[:len(x) // N * N].reshape(-1, N)


def frame_rms(frames):
    """Broadband RMS per frame -- every hertz the microphone could hear.

    This is the gate Lab 4 used to run on, and the reason it stopped: in a room
    with a furnace, most of what this measures sits below the lowest band the
    detector ever looks at. Kept because seeing it next to band_rms() is the
    clearest way to understand why that change was made.
    """
    return np.sqrt((frames * frames).mean(axis=1))


def power_spectrogram(frames):
    """|X(k)|^2 per frame, windowed and scaled exactly as the detector does.

    Returns (n_frames, N // 2 + 1). Bin k is centered at k * BIN_HZ.
    """
    return np.abs(np.fft.rfft(frames * WINDOW, axis=1)) ** 2


def band_energy(power, edges):
    """Summed power per band per frame -- the detector's `acc`, before the log.

    Returns (n_frames, len(edges) - 1).
    """
    return np.stack([power[:, edges[b]:edges[b + 1]].sum(axis=1)
                     for b in range(len(edges) - 1)], axis=1)


def band_rms(power, edges):
    """Lab 4's loudness gate: an RMS measured over ONLY the bands it matches on.

    Same 24-bit units as frame_rms(), so SPEECH_FLOOR means the same thing
    against either one -- which is what makes the two curves comparable on a
    plot instead of merely adjacent.
    """
    return np.sqrt(BAND_RMS_SCALE * band_energy(power, edges).sum(axis=1))


def feature_vectors(power, edges, mean_subtract=True):
    """The vector Lab 4 actually correlates: log band energy, mean removed.

    Returns (n_frames, n_bands).

    The mean subtraction is not cosmetic and leaving it out is a genuinely
    instructive failure. Raw log energies all land within a few percent of each
    other, so every frame -- speech, silence, furnace -- correlates with every
    other frame at about 1.00 and the detector has no discriminative power at
    all. What survives the subtraction is spectral SHAPE, which is also what
    makes the score independent of how loudly the phrase was spoken.
    """
    e = band_energy(power, edges)
    widths = np.array([edges[b + 1] - edges[b]
                       for b in range(len(edges) - 1)], dtype=np.float64)
    v = np.log1p(e / widths)
    if mean_subtract:
        v = v - v.mean(axis=1, keepdims=True)
    return v


def noise_floor(rms):
    """A take's own quiet level: the FLOOR_PERCENTILE of its frame RMS."""
    return float(np.percentile(rms, FLOOR_PERCENTILE))


def phrase_extent(rms):
    """(floor, first_frame, last_frame) for the speech in one take.

    first/last are None when nothing in the take clears the gate.
    """
    floor = noise_floor(rms)
    on = np.where(rms > floor * LOUD_RATIO)[0]
    if not len(on):
        return floor, None, None
    return floor, int(on[0]), int(on[-1])


def frame_classes(rms):
    """(loud, quiet) boolean masks over frames, by each take's own floor."""
    floor = noise_floor(rms)
    return rms > floor * LOUD_RATIO, rms <= floor * QUIET_RATIO


def spectrum_shares(takes, edges):
    """Share of energy per band for speech and for room, across every take.

    `takes` is a sequence of (name, frames). Both arrays sum to 1.
    """
    n = len(edges) - 1
    speech = np.zeros(n)
    quiet = np.zeros(n)
    for _, f in takes:
        rms = frame_rms(f)
        loud, still = frame_classes(rms)
        power = power_spectrogram(f)
        for b in range(n):
            sl = slice(edges[b], edges[b + 1])
            speech[b] += power[loud][:, sl].sum()
            quiet[b] += power[still][:, sl].sum()
    return speech / speech.sum(), quiet / quiet.sum()


def sweep(speech, noise, hz, steps=6):
    """What raising BAND_LO_HZ to each band edge in turn would cost and buy.

    Returns a list of (cutoff_hz, speech_kept, noise_kept, snr_change_db),
    fractions rather than percents. Judge these on speech kept as well as on
    dB: a band that buys 1 dB while throwing away a third of the phrase is a
    bad trade, and the ratio alone will not tell you so.
    """
    base = np.log10(speech.sum() / noise.sum())
    rows = []
    for k in range(min(steps, len(speech))):
        s, n = speech[k:].sum(), noise[k:].sum()
        rows.append((hz[k], float(s), float(n),
                     float(10 * (np.log10(s / n) - base))))
    return rows
