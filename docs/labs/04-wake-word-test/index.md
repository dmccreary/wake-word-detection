---
title: "Lab 4: Wake Word Test"
description: Enroll a custom trigger phrase and detect it in a live microphone stream — why "Hey Pico" is the reference phrase, and what a fixed-length template can and cannot do
---

# Lab 4: Wake Word Test

**Time:** ~60 minutes  |  **Prerequisites:** [Lab 1](../01-setup/index.md), [Lab 2](../02-fft-test/index.md), [Lab 3](../03-mic-calibration/index.md)  |  **Hardware:** the full kit

## What You'll Build

A detector that listens to the microphone continuously — never stopping, never waiting for a
button — and lights up the display when it hears one specific phrase you taught it yourself.

## Learning Objectives

- **Choose** a wake phrase on acoustic grounds rather than taste
- **Explain** why some phrases are far easier to detect than others
- **Enroll** a custom trigger phrase from your own voice
- **Describe** how a spectrum becomes a compact, loudness-independent feature vector
- **Justify** the detection threshold from measured data instead of guesswork
- **Measure** the detector's false accepts against a deliberate confusable list
- **Recognize** the time-warping limitation of fixed-length template correlation

## Concepts Introduced

| Concept | What it means here |
|---|---|
| Wake word / trigger phrase | The one phrase that moves the device out of idle |
| Enrollment | Recording your phrase to build a reference template |
| Template correlation | Scoring live audio against a stored pattern |
| Log-spaced band energies | Collapsing 128 FFT bins into 12 speech-shaped bands |
| Cepstral mean normalization | Removing the common offset so only spectral *shape* remains |
| Voice activity gate | A loudness floor from [Lab 3](../03-mic-calibration/index.md), so silence cannot match silence |
| False accept / false reject | The two failure modes, traded against each other |
| Refractory period | Ignoring input briefly after a detection |
| Time warping | Why pace consistency matters, and what a real system does about it |

## Background

### Choosing a wake phrase

The phrase is your first and cheapest lever on accuracy — you get to pick it before writing a
line of detection code. The reference phrase for this course is **"Hey Pico"**.

That is not an arbitrary choice. Template correlation scores *spectral shape over time*, so the
best phrases are the ones whose shape changes the most. "Hey Pico" — /heɪ ˈpiː.koʊ/ — does
several things well at once:

- **Two plosives.** The /p/ and /k/ each produce a brief closure followed by a burst. Those
  near-silent frames are strong temporal anchors that a template locks onto easily.
- **A front-to-back vowel sweep.** /iː/ has its formants far apart (roughly 270 Hz and 2300 Hz —
  energy in a low band *and* a high band, with little between). /oʊ/ has both formants low and
  close together (roughly 450 and 750 Hz). Across the 12 bands this lab uses, that is a large and
  unmistakable change.
- **Three syllables** — the same length as "Alexa" and "Hey Siri". Long enough to be distinctive,
  short enough to say the same way twice.
- **A familiar shape.** "Hey X" needs no explanation to a user.

!!! tip "Why one phrase for the whole class"
    If everyone enrolls the same phrase, false-accept and false-reject numbers are directly
    comparable between students, and an instructor can build a single shared test set. That is
    worth more than letting everyone pick a favorite. Enroll "Hey Pico" first and get your
    baseline numbers; *then* experiment.

### What to avoid

| Avoid | Why |
|---|---|
| "Alexa", "Hey Siri", "OK Google", "Cortana" | Sets off every real assistant in the room — **and their spoken replies feed back into your microphone and corrupt your false-accept measurements.** It looks like a detector bug and is not |
| A single syllable ("Pico" alone) | Around 350 ms is too few frames to be distinctive; false accepts climb sharply |
| Anything starting with a vowel | Onsets are harder to locate consistently |
| A phrase you say in ordinary conversation | Every use is a false accept by construction |

The one genuine weakness of "Hey Pico" is that **"hey" is common in speech**. It matters less than
it looks: scoring is the mean dot product across the *whole* window, so a stray "hey" fills only
about a third of it and the rest still has to match. The real risk is "hey" followed by a
similar-rhythm two-syllable word — which is exactly what the test list below is for.

### How the detector works

1. Read 256 samples — 20 ms of sound. This never stops.
2. Window, FFT, and collapse 128 bins into 12 log-spaced band energies.
3. Take the log of each band, **subtract the frame's mean log-energy**, then normalize to unit
   length.
4. Push the result into a ring buffer of the last 40 frames (800 ms).
5. Score against the enrolled template: the mean dot product, frame by frame. Both vectors are
   unit length, so a perfect match is 1.0.
6. Above threshold **and** loud enough to be speech → wake.

!!! warning "Step 3 looks skippable. It is not."
    Raw log band energies for ordinary speech all land within a few percent of each other —
    around 25 to 28. Without subtracting the mean, every normalized vector points in nearly the
    same direction and **everything scores about 1.00, silence included**. The detector still
    fires, so it looks like it works, while having no discriminative power whatsoever.

    Removing the common offset is what leaves only the spectral *shape* — the part that actually
    identifies a phrase. Real MFCC pipelines do the same thing under the name **cepstral mean
    normalization**.

### Where the threshold number comes from

The default threshold is **0.70**, and it was chosen from a measurement rather than taste.

A fixed-length template has no **time warping**: it compares frame 7 with frame 7, always. So when
a phrase is spoken faster than it was enrolled, every frame after the first slips out of
alignment and the score falls off a cliff. Measured against an enrollment that filled the whole
800 ms window:

| Phrase fills | Duration | Score |
|---|---|---|
| 100% of window | 800 ms | **0.97** |
| 95% | 760 ms | 0.84 |
| 90% | 720 ms | 0.73 |
| 85% | 680 ms | 0.66 |
| 80% | 640 ms | 0.49 |
| 70% | 560 ms | 0.31 |
| *impostor: same sounds, different order* | 800 ms | *0.52* |

Read those two ends together. The threshold has to sit **above ~0.52** to reject the impostor, but
**low enough to accept the enrolled speaker varying their pace** by the ±10% a human naturally
does. 0.70 accepts down to about 88% fill and still clears the impostor by roughly 0.18.

The obvious-looking higher number is the wrong one: at 0.80, a perfectly good utterance said
10% quickly is rejected.

!!! note "This is the honest limit of the technique"
    Sensitivity to speaking rate is *the* weakness of fixed-window template correlation, and it is
    why production systems use dynamic time warping or a trained model instead. This lab does not
    hide it — it measures it, reports window fill at enrollment so you can correct your pace, and
    leaves DTW as a challenge below.

## Procedure

!!! warning "Calibrate first"
    This lab uses `SPEECH_FLOOR` from `config.py`, and that constant is **measured**, not chosen —
    [Lab 3](../03-mic-calibration/index.md) produces it for your room and your speaking distance.
    Running on the shipped default is the single most common reason the detector appears not to
    hear you. If you have not calibrated, do that first.

### Step 1 — Run the detector

```python
--8<-- "src/labs/04-wake-word-test/04-wake-word-test.py"
```

### Step 2 — Enroll "Hey Pico"

| Button | In LISTEN | In ENROLL |
|---|---|---|
| MODE | switch to ENROLL | switch to LISTEN |
| UP | raise threshold (stricter) | record one repetition |
| DOWN | lower threshold (looser) | forget all enrollments |

Press **MODE** to reach ENROLL, then **UP**, and say "Hey Pico" after the countdown. Repeat three
to five times.

After each take the display reports **window fill** — what fraction of the 800 ms window your
voice actually occupied. Aim for **85–99%**. Below that the table above shows exactly what happens
to your score.

!!! tip "Pace, not volume, is what you are practicing"
    The feature vectors are loudness-normalized, so speaking louder changes nothing. Speaking at a
    *different speed* changes everything. Enroll all your takes at the same deliberate pace.

### Step 3 — Detect

Press **MODE** to return to LISTEN and say "Hey Pico". The score bar tracks live; the tick mark
shows the threshold. On a match the display inverts and the speaker beeps.

### Step 4 — Measure false rejects

Say the phrase 20 times, naturally. Count the misses. That is your **false reject rate** at the
current threshold.

### Step 5 — Measure false accepts with a real test list

Now try to *break* it. Read each of these ten aloud five times and count how many trigger it:

| # | Utterance | Why it is on the list |
|---|---|---|
| 1 | "Hey, listen" | "hey" + two syllables, same rhythm |
| 2 | "Hey, Nico" | near-minimal pair for "Pico" |
| 3 | "Hey, kiddo" | same rhythm, two plosives |
| 4 | "Hey, people" | shared /p/ and vowel |
| 5 | "Peek a boo" | phonetically closest common phrase |
| 6 | "Hey there" | the bare common prefix |
| 7 | "Pico" alone | phrase without its prefix |
| 8 | "Hey Pico" said fast | *should* fail — the time-warping limit |
| 9 | normal conversation, 2 minutes | the realistic background case |
| 10 | a TV or podcast, 2 minutes | continuous speech-shaped noise |

Rows 1–7 are false accepts if they fire. **Row 8 is different** — it is a false *reject*, and a
known limitation rather than a bug. Rows 9 and 10 are the numbers that matter most for a device
meant to sit in a room all day.

### Step 6 — Move the threshold and re-measure

Change the threshold with **UP**/**DOWN** and repeat steps 4 and 5. Plot false rejects against
false accepts. You have just drawn the tradeoff curve that every wake-word system in existence
lives on, from your own measurements.

## Expected Output

```
Lab 4: Wake Word Test
frame = 256 samples = 20.0 ms; window = 40 frames = 800 ms
bands = 12, bins 3..120

MODE cycles LISTEN/ENROLL. Enroll your phrase 3-5 times, then listen.

enrolled sample 1  (window fill 92%)
enrolled sample 2  (window fill 88%)
enrolled sample 3  (window fill 90%)
mode -> LISTEN
WAKE WORD DETECTED  score=0.812  rms=241533  #1
WAKE WORD DETECTED  score=0.774  rms=198004  #2
```

On exit it reports the worst per-frame processing time and any frame overruns.

!!! warning "Overruns invalidate your accuracy numbers"
    An overrun means the work for one frame took longer than the 20 ms of audio it represents, so
    audio was dropped. Any false-reject rate measured during a run with overruns is partly a
    timing artifact. Fix the budget before trusting the accuracy.

## Verifying the math without hardware

Every number in this writeup is reproducible on a laptop:

```bash
python3 src/tools/test_detector_math.py
```

It imports the real detector, stubs the hardware, and drives it with synthetic speech. Run it
after any change to feature extraction or scoring.

The failure signature worth memorizing: **if every row scores about 1.00**, the mean-subtraction
in step 3 has been lost and the detector has no discriminative power — even though it still fires.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Everything triggers, including silence | Mean-subtraction lost from the feature vector | Run the host-side check; expect ~1.00 everywhere |
| Score never rises above ~0.3 | Pace differs from enrollment | Check window fill; re-enroll at a consistent pace |
| Nothing registers at all | `SPEECH_FLOOR` too high for your room | Re-run [Lab 3](../03-mic-calibration/index.md) and paste its value into `config.py` |
| Score sits high constantly | Threshold too low, or gate too permissive | Raise threshold; check `SPEECH_FLOOR` |
| Triggers repeatedly on one utterance | Refractory period too short | Raise `REFRACTORY_MS` |
| Fires when the speaker beeps | Self-trigger — the device hearing itself | Expected; this is Module 5's whole topic |
| `OVR` on the display, count rising | Frame overruns; audio being dropped | Lower `TEMPLATE_FRAMES` or `BANDS` |
| Detects for you, not for a classmate | Single-speaker enrollment | Expected; enroll multiple speakers |

## Challenges

1. **Draw the curve.** Measure false accepts and false rejects at five thresholds from 0.55 to
   0.90 and plot them. Where would *you* set it for a device in your kitchen, and why?
2. **Test a bad phrase.** Enroll "Pico" alone and re-run the test list. Quantify how much worse a
   one-word trigger is than a three-syllable one.
3. **Beat the time-warping limit.** Implement dynamic time warping, or score against several
   time-scaled copies of the template and keep the best. Re-measure the fill-versus-score table
   and show how much flatter you made it.
4. **Multi-speaker enrollment.** Enroll three people. Does the averaged template help everyone, or
   blur into serving no one well? Measure it rather than guessing.
5. **Pick the bands apart.** Try 8 bands and 16. What does each do to the margin between the
   enrolled phrase and the impostors, and to the per-frame processing time?

## Check Your Understanding

1. Why does subtracting the mean log-energy matter so much, and what is the symptom when it is
   missing?
2. Why does a loudness gate matter even though the score already distinguishes phrases?
3. Explain, from the fill-versus-score table, why 0.80 is a worse default threshold than 0.70.
4. Row 8 of the test list is a false reject rather than a false accept. Why does that distinction
   matter when reporting results?
5. What makes "Hey Pico" easier to detect than "Pico", in terms of what the template actually
   stores?

---

**Previous:** [Lab 3: Microphone Calibration](../03-mic-calibration/index.md)
