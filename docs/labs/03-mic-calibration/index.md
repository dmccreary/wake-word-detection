---
title: "Lab 3: Microphone Calibration"
description: Measure your room's noise floor and your own speaking level, and compute the one constant the wake-word detector cannot work without
---

# Lab 3: Microphone Calibration

**Time:** ~45 minutes  |  **Prerequisites:** [Lab 1](../01-setup/index.md), [Lab 2](../02-fft-test/index.md)  |  **Hardware:** Pico 2 and the INMP441 microphone

## What You'll Build

A characterization of your microphone in *your* room, producing one number — `SPEECH_FLOOR` —
that Lab 4's detector depends on, plus the environment description that makes Lab 4's accuracy
results reportable at all.

## Learning Objectives

- **Measure** a room's noise floor and express it in dBFS and estimated dB SPL
- **Measure** your own speaking level at the distance you will actually use
- **Compute** a signal-to-noise ratio and judge whether a room is workable
- **Derive** a voice-activity threshold from data rather than choosing one
- **Verify** you are not clipping the microphone
- **Identify** which frequency bands your room's noise occupies
- **Explain** why an accuracy result without its noise environment is not a result

## Concepts Introduced

| Concept | What it means here |
|---|---|
| Noise floor | The level the room sits at with nobody talking |
| dBFS | Level relative to full scale; 0 dB is the maximum, everything else negative |
| Microphone sensitivity | The datasheet figure that maps dBFS onto estimated dB SPL |
| Signal-to-noise ratio | How far your voice rises above the room |
| Voice activity gate | The threshold below which audio is not considered speech |
| Headroom and clipping | Running out of range at the top instead of the bottom |
| Noise spectrum | *Where* in frequency the room's noise sits, not just how much |
| Environment reporting | Stating the conditions a measurement was taken under |

## Background

### Why this lab exists

Lab 4's detector compares normalized spectral shapes. Normalization is what makes it
loudness-independent — the same phrase said loudly and softly produces the same feature vector.

That strength is also a hole. **Normalized room noise correlates with normalized room noise
perfectly well.** Without a loudness gate, a silent room produces feature vectors that score
against the template all day long. The gate — `SPEECH_FLOOR` — is what makes the detector ignore
a room that is merely sitting there.

Guessing that constant fails in both directions, and each failure impersonates a different bug:

| If the gate is | Symptom | What you would wrongly blame |
|---|---|---|
| Too **high** | "It can't hear me" | The threshold, the enrollment, the phrase |
| Too **low** | "It fires at nothing" | The threshold, the template, the bands |

In both cases the threshold knob is the wrong knob, and you can lose an afternoon to it.

!!! note "The gate is the first of two defenses, not the only one"
    A room loud enough to pass the gate still has to *score* against the template, and ordinary
    room noise scores near zero. Measured on synthetic audio: a 40 dB SPL room is gated out
    outright, while a 60 dB SPL room passes the gate and then scores 0.01 against a threshold of
    0.70. The gate's job is to stop the scorer from ever seeing quiet noise — not to be the only
    thing standing between you and a false accept.

!!! warning "The shipped default was wrong, and this is how we know"
    The first version of this kit hardcoded `SPEECH_FLOOR = FULL_SCALE * 0.004`. The INMP441 is
    specified at **−26 dBFS for a 94 dB SPL input**, which makes the conversion
    `dBFS = SPL − 120`. Running that constant through it:

    \[
    20\log_{10}(0.004) = -48\ \text{dBFS} \quad\Rightarrow\quad 72\ \text{dB SPL}
    \]

    72 dB SPL is a raised voice at arm's length. Ordinary conversation at half a metre is about
    66 dB SPL, and at a metre about 60 — **both below the gate**. The detector would have demanded
    you lean in and speak up, and every student would have experienced that as a broken detector.

    The default is now `0.0008` (≈58 dB SPL), which is a *better guess* — and still only a guess
    about your room. That is what this lab replaces.

### dBFS, and why levels are logarithmic

A level here is expressed relative to full scale:

\[
\text{dBFS} = 20 \log_{10}\!\left(\frac{\text{RMS}}{\text{full scale}}\right)
\]

Full scale is 0 dB and everything real is negative. Decibels are used because hearing and acoustic
levels span an enormous range — a quiet room and a shout differ by a factor of several thousand in
amplitude, which is unreadable as a raw number and obvious as ~40 dB.

The INMP441 datasheet's sensitivity figure lets you *estimate* sound pressure level from that:

\[
\text{dB SPL} \approx \text{dBFS} + 120
\]

!!! note "Estimated, not calibrated"
    That conversion uses a nominal datasheet figure. Individual units vary by about ±1 dB, and
    nothing here is checked against a reference source. The SPL numbers are useful for judging
    "is this a quiet room or a busy one" and useless as absolute acoustic measurements. The dBFS
    numbers, by contrast, are exactly what the detector actually sees.

### Why the *worst* noise frame matters more than the average

The lab reports both the median and the maximum frame level during the quiet measurement, and
sets the gate from the maximum.

False accepts are not caused by a room's average level. They are caused by the fridge compressor
kicking in, a chair creaking, a door down the hall. Those are single loud frames in an otherwise
quiet recording, and the median hides them completely. A gate placed on the median lets every one
of them through.

### Where the recommendation comes from

The recommended gate sits at the **geometric mean** of the noise and speech levels — halfway
between them *in decibels*, which is the right kind of halfway for a logarithmic quantity — then
gets clamped:

- never below **4× the worst noise frame** (~12 dB of margin over the real enemy)
- never above **70% of your speech level**, so it cannot gate out your own voice

## Procedure

### Step 1 — Run the calibration program

```python
--8<-- "src/labs/03-mic-calibration/03-mic-calibration.py"
```

**MODE** cycles the five tests, **UP** runs the current one, **DOWN** clears everything. Each
measurement takes five seconds.

### Step 2 — NOISE: measure the room

Press **UP** and stay quiet for five seconds. Do not hold your breath or freeze — sit as you
normally would. You are characterizing the room you will actually use, not a recording booth.

Note both numbers. The gap between median and max tells you how *steady* your room is.

### Step 3 — SPEECH: measure yourself

Press **MODE**, then **UP**, and repeat "Hey Pico" for five seconds at the distance and volume
you intend to use. Distance matters more than anything else here — sound pressure falls about
**6 dB every time you double the distance**, so 1 m is roughly 6 dB quieter than 50 cm.

The lab reports the **top decile** rather than the mean, because most frames of any utterance are
the quiet parts between syllables. What matters is how loud the loud parts get.

### Step 4 — CLIP: check headroom

Press **MODE**, then **UP**, and speak as loudly as you plausibly might. Peak should stay
comfortably under 100% of full scale. Above about 90%, you are clipping — and a clipped waveform
grows harmonics that were never in the room, which corrupts every band energy downstream.

### Step 5 — SPECTRUM: find where the noise lives

Press **MODE**, then **UP**, and be quiet again. The console prints a per-band breakdown.

If the loudest noise is in the lowest bands, you have low-frequency room rumble — HVAC, traffic,
a computer fan. That noise is doing nothing but degrading the detector, because very little speech
information lives below ~200 Hz. Raising `BAND_LO_HZ` in Lab 4 above the offending band is a more
effective fix than any threshold change.

### Step 6 — RESULT: record and apply

Press **MODE** to reach RESULT. The console prints the constant to paste into
[`config.py`](https://github.com/dmccreary/wake-word-detection/blob/main/src/config.py):

```python
SPEECH_FLOOR = FULL_SCALE * 0.00046
```

**Write down the room and distance too.** Lab 4 asks you to report a false-accept rate, and a
false-accept rate without its noise environment is not a result — it is a number. Commercial
engines are quoted this way for exactly this reason: Espressif publishes WakeNet's false-accept
figure *"in typical home background noise"*, not bare.

## Expected Output

Approximate values for a quiet home room, speaking at about 50 cm. Your room is the authority:

```
Lab 3: Microphone Calibration
MODE cycles tests, UP runs the current one, DOWN clears all.
Each measurement takes 5 seconds.

noise floor : median      839  (-80.0 dBFS, ~40 dB SPL)
              worst      2100  (-72.0 dBFS)  <- the number that matters
speech      : top-decile 16737  (-54.0 dBFS, ~66 dB SPL)
              peak       31500  (-48.5 dBFS)
headroom    : peak sample 393587 = 4.7% of full scale

==========================================================
CALIBRATION RESULT
==========================================================
room noise  : -80.0 dBFS  (~40 dB SPL)
your speech : -54.0 dBFS  (~66 dB SPL)
SNR         : 26.0 dB

Paste this into config.py:

    SPEECH_FLOOR = FULL_SCALE * 0.00046

(currently 0.00080)
```

## Interpreting Your SNR

| SNR | What it means |
|---|---|
| **> 25 dB** | Comfortable. The gate has plenty of room between noise and speech |
| **15–25 dB** | Workable. Expect some tuning of the Lab 4 threshold |
| **< 15 dB** | Hard room. Move closer to the microphone or find a quieter spot — no threshold choice rescues this, and Lab 4's false-reject rate will be poor no matter what you do |

If your SNR is low, the fix is physical, not numerical. Halving your distance to the microphone
buys about 6 dB, which is worth more than any amount of parameter fiddling.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Noise floor reads −120 dBFS | Microphone returning zeros | L/R to GND; re-run Lab 1's mic check |
| Noise floor above −60 dBFS | Genuinely noisy room, or mic near a fan | Move the board; re-measure |
| Speech level below noise | Measurements run in the wrong order | Press DOWN to clear and redo |
| Clipping at normal volume | Speaking directly into the port | Back off to 20 cm or more |
| Noise concentrated in the lowest band | HVAC or fan rumble | Raise `BAND_LO_HZ` in Lab 4 |
| Recommendation above your speech level | SNR too low to place a gate | The clamp caps it at 70% of speech; the room is the problem |

## Challenges

1. **Distance law.** Measure your speech level at 25 cm, 50 cm, 1 m, and 2 m. Does it fall ~6 dB
   per doubling as theory predicts? Plot it. Where does your SNR cross below 15 dB?
2. **Break the room.** Re-measure the noise floor with a fan, a window open, or music playing.
   How much does the recommended gate move, and does the old value still work?
3. **Median versus max.** Compute what the gate would be if it used the median noise frame instead
   of the worst. Then run Lab 4 with it and count false accepts. Was the stricter rule worth it?
4. **Move the low edge.** If your noise is low-frequency, raise `BAND_LO_HZ` to 250 or 300 Hz and
   re-run Lab 4's confusable test list. Did false accepts drop? Did false rejects rise?
5. **Two rooms, one detector.** Calibrate and enroll in a quiet room, then run Lab 4 in a noisy
   one without re-calibrating. Quantify the damage. This is exactly what happens to a real device
   that gets moved.

## Check Your Understanding

1. Why does a detector that normalizes for loudness still need a loudness gate?
2. Convert `FULL_SCALE * 0.004` to dBFS and to estimated dB SPL. Why was it a poor default?
3. Why does the lab set the gate from the *worst* noise frame rather than the median?
4. Why is the speech level reported as a top decile rather than an average?
5. Your friend reports a 3% false-accept rate. What single piece of information do you need before
   that number means anything, and why?

---

**Next:** [Lab 4: Wake Word Test](../04-wake-word-test/index.md)  |  **Previous:** [Lab 2: FFT Test](../02-fft-test/index.md)
