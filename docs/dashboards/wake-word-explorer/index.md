---
title: Wake Word Explorer
description: Ten recorded takes of "Hey Pico" as waveforms, spectra and band energies — sweep BAND_LO_HZ and watch the furnace disappear from under the phrase
hide:
  - toc
---

# Wake Word Explorer

**Uses:** ten takes recorded by `src/labs/record-wake-words.py`
&nbsp;|&nbsp; **Related:** [Lab 3](../../labs/03-mic-calibration/index.md),
[Lab 4](../../labs/04-wake-word-test/index.md)

Lab 4 can only tell you what it already believes — a score, a threshold, an RMS
it measured with settings that may themselves be wrong. This dashboard shows
the recordings those beliefs were formed from, so you can check them.

<div class="iframe-container dashboard-embed">
<iframe src="main.html" height="1500" scrolling="no"></iframe>
</div>

[Open full screen](main.html){ .md-button }

## What you are looking at

**Overview.** Ten takes stacked the way Audacity stacks tracks. Each row is one
three-second recording: the waveform on the left, and on the right the mean
spectrum of that take's speech frames (blue) against its quiet frames (orange).
Click any strip to open it full width.

**Drill-down.** One take at a time — the waveform with its envelopes, a
spectrogram with the twelve band edges drawn across it, the band energies Lab 4
actually matches on, and the mean spectrum enlarged.

**The `BAND_LO_HZ` slider** is the control that matters. It moves the bottom of
the detector's twelve log-spaced bands, exactly as `--lo=` does on
`analyze-wake-words.py`, and everything on screen follows: the band edges, the
band-limited RMS envelope, the greyed-out region of the spectrum, and the
verdict strip along the top. Tick **through the filter** and press play to hear
the same decision.

## Four things worth finding

!!! tip "1. The gate the detector uses is not the gate you would have guessed"
    Turn on both RMS envelopes. **Broadband RMS** (grey, dotted) counts every
    hertz the microphone can hear. **Band RMS** (blue) counts only the
    350–6000 Hz the detector has bands for.

    At the peak of the phrase the two are 0.3 dB apart — speech lives above
    350 Hz, so the filtering costs it essentially nothing. On the quiet frames
    between words they are **15.1 dB** apart: broadband sits at 6,621 and band
    RMS at 1,163. That gap is the furnace fan, and it is energy the matcher
    never looks at.

    Gating on the broadband number therefore sets `SPEECH_FLOOR` almost
    entirely from noise the detector cannot see. Switching to the band-limited
    gate moves the room from 16.5 dB below the threshold to **31.6 dB** below
    it, for no cost to speech at all. That is the change Lab 4 v1.6.0 makes.

!!! tip "2. Where 350 Hz came from"
    Sweep the slider from 150 Hz upward and watch the verdict strip. Against
    the takes' own quiet frames, 350 Hz keeps **84.9%** of the phrase while
    discarding **81%** of the room. Against Lab 3's measured furnace spectrum
    it is better still: 89% of the noise gone, **+9.0 dB**.

    Keep going. 500 Hz scores marginally higher on paper — and buys that last
    0.8 dB by throwing away another 29% of the phrase. The ratio alone picks
    500; the ratio judged alongside speech kept picks 350. Push to 700 Hz and
    the phrase is essentially gone.

    Now switch **Noise reference** to the Lab 3 furnace spectrum at a cutoff
    like 300 or 400 Hz. It refuses to answer, and says why: Lab 3 measured its
    spectrum on its own band edges, and comparing one band of speech against a
    different band of noise would produce a confident, meaningless number.

!!! tip "3. Why the mean subtraction is not optional"
    In the drill-down, turn **mean-subtracted bands** off. The band-energy
    panel goes nearly uniform — every frame looks like every other frame,
    because raw log energies all land within a few percent of each other.

    A detector correlating those vectors scores silence against speech at about
    1.00 and has no discriminative power at all. Subtracting each frame's mean
    log-energy is what leaves spectral *shape* behind, and shape is also what
    makes the score independent of how loudly you spoke.

!!! tip "4. Take 07 is the interesting failure"
    Nine takes hold the phrase inside 500–760 ms. Take 07 measures **1,900 ms**
    because something after the phrase — a chair, a breath, the furnace
    stepping up — cleared the gate and dragged the "last frame above threshold"
    to frame 106.

    This is what a fixed 32-frame template window is up against, and it is why
    the recommendation is built on the *median* span rather than the maximum.
    Open take 07, then compare it with take 09.

## Reading the plots

| Marking | Meaning |
|---|---|
| Grey vertical bars | The waveform, min and max per column, in 24-bit units |
| Blue envelope | Band-limited RMS — the loudness Lab 4 gates on |
| Grey dotted envelope | Broadband RMS — every hertz, including the furnace |
| Grey dotted horizontal | That take's own noise floor (its 20th-percentile frame) |
| Red dashed horizontal | `SPEECH_FLOOR`, 44,460, measured in Lab 3 |
| Orange shading | The phrase, gated at the take's floor + 10 dB |
| Blue vertical lines | The twelve band edges at the current `BAND_LO_HZ` |
| Grey block on the spectrum | Everything the current cutoff throws away |

All levels are in **24-bit units** — the same units `calibration.json` and Lab
4's console print, so a number here can be compared directly against a number
there.

## Where the numbers come from

Every measured value is computed by
[`src/tools/wakeword_analysis.py`](https://github.com/dmccreary/wake-word-detection/blob/main/src/tools/wakeword_analysis.py),
the module that also backs the command-line tool:

```bash
python3 src/tools/analyze-wake-words.py docs/sounds src/labs/results/calibration.json
```

The dashboard and that script therefore cannot disagree — the printed table and
the picture beside it are the same function call. `build-explorer-data.py`
ships a power spectrogram of every take, and the browser sums subsets of its
bins to follow the slider. That is addition, not analysis, and Python ships a
checksum of each sum: open the browser console and you should see

```
Wake Word Explorer: 10 takes x 16 cutoffs agree with numpy to 0.02 dB.
```

!!! warning "One thing the plots and the ear do differently"
    The plots cut frequency bins off square. Playback uses two cascaded biquad
    high-pass filters — 24 dB per octave, not a brick wall — because that is
    what a browser can do in real time. It is close enough to hear which side
    of the cutoff the phrase lives on, which is the point, but the audio is not
    the exact signal the plots describe.

## Using your own recordings

Record ten takes on the board, fetch them, and rebuild:

```bash
mpremote connect <port> run src/labs/record-wake-words.py
```

```bash
mpremote connect <port> fs cp -r :sounds docs/
```

```bash
python3 src/tools/build-explorer-data.py
```

The takes in `docs/sounds/` are committed on purpose, so the dashboard has real
data the first time you open it. Replacing them with your own voice, in your
own room, is the point of the exercise — the 350 Hz answer above is a
measurement of one basement with one furnace, not a constant.
