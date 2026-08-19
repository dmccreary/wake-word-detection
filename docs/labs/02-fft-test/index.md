---
title: "Lab 2: FFT Test"
description: Measure how much of one audio frame's time budget an FFT consumes, and decide from that number whether a continuous wake-word pipeline is possible at all
---

# Lab 2: FFT Test

**Time:** ~45 minutes  |  **Prerequisites:** [Lab 1](../01-setup/index.md)  |  **Hardware:** Pico 2 and the INMP441 microphone

## What You'll Build

A benchmark that answers one question with a number: **how much of one audio frame's time budget
does an FFT actually consume?**

Lab 4 needs to turn a live microphone stream into a sequence of spectra, forever, without ever
missing a sample. This lab decides in advance whether that is possible — before you write it.

## Learning Objectives

- **Derive** a real-time frame budget from a sample rate and a frame size
- **Measure** execution time on hardware rather than estimating it
- **Explain** why a warm-up run must be discarded
- **Distinguish** the mean from the best-of-N, and say what each is good for
- **Separate** capture cost from processing cost
- **Decide**, from a measured percentage, whether a continuous pipeline will fit
- **Predict** a result before measuring it, and account for the gap

## Concepts Introduced

| Concept | What it means here |
|---|---|
| Real-time budget | Frame duration is a deadline, not a target |
| Frame size vs. sample rate | 256 samples at 12,800 Hz *is* 20 ms of sound |
| Warm-up run | The first call pays one-time costs the steady state will not |
| Mean vs. best-of-N | Typical behavior vs. the machine's true capability |
| Garbage-collection interference | Why `gc.collect()` goes *before* the timed region |
| DWT cycle counter | Cycle-accurate timing, verified before it is trusted |
| Headroom | Budget left over for everything the benchmark did not measure |

## Background

### The budget is not a matter of opinion

Every lab in the prerequisite course ran the FFT on demand — press a button, capture a frame, look
at the spectrum. If it took a while, you waited.

A wake-word detector cannot work that way. It runs the same capture-and-analyze pipeline
continuously, and audio arrives whether or not you are ready for it. That converts a preference
into a deadline:

$$
\text{frame duration} = \frac{N}{f_s} = \frac{256}{12800} = 20\ \text{ms}
$$

256 samples at 12,800 Hz **is** 20 ms of sound. Not approximately — exactly. If processing one
frame takes longer than 20 ms, the next frame's audio arrives while you are still working on the
last one, and it is gone. You cannot get it back, and no amount of catching up later recovers it.

!!! note "Why N = 256 and not 512"
    The prerequisite course used 512-point transforms at 12,800 Hz, giving 40 ms frames. Speech
    changes faster than that. A 20 ms frame is a standard speech-analysis hop, so Lab 4 uses
    N = 256 — which also halves the deadline, making this measurement matter more, not less.

### Measure capture and processing separately

The lab times two different things, and conflating them would be a mistake:

- **`mic.readinto()`** should take about **20 ms** — and that is not overhead. Waiting for 20 ms of
  sound *takes* 20 ms, because the microphone delivers audio in real time. This measurement is a
  sanity check that the mic is streaming at the rate you think it is, not a cost to optimize.
- **The FFT** is the part that competes for the budget. It is the number that decides whether Lab 4
  is possible.

### Why the first run is thrown away

The benchmark runs the FFT once and discards the result before timing anything. The first call
pays costs the steady state never will — code paths touched for the first time, caches cold,
allocations made once. Including it would inflate the mean with a cost that only ever happens once.

This is the same warm-up discipline the prerequisite course insisted on, applied here because it
matters just as much when the answer is a go/no-go decision.

### Mean and best, and why both appear

The benchmark reports both:

- **Mean** — what the pipeline will typically experience. This is the number to judge the budget
  against, because a pipeline has to survive typical frames, not just lucky ones.
- **Best-of-N** — the machine's genuine capability with interference stripped away. If mean and
  best diverge sharply, something is interfering, and that gap is worth investigating before you
  trust either number.

`gc.collect()` is called *before* each timed region, deliberately. Garbage collection is real work
that a real pipeline pays for — but letting it fire at a random point *inside* a timed window
turns a clean measurement into a noisy one. Forcing it beforehand makes the timed region measure
the FFT rather than the allocator.

### The 50% rule

The verdict column is stricter than "did it fit":

| Verdict | Condition |
|---|---|
| `YES` | under 50% of budget |
| `TIGHT` | 50–100% |
| `NO` | over 100% |

An FFT using 90% of the frame technically fits, and is still useless — because Lab 4 also has to
extract band energies, normalize them, and score 40 frames against a template, none of which this
benchmark measures. Anything above roughly half the budget leaves no room for the rest of the
pipeline.

## Procedure

### Step 1 — Predict first

Before running anything, write down your prediction. The prerequisite course measured, on the same
chip at 512 points:

| Implementation | 512-point time |
|---|---|
| Pure-Python FFT | 140 ms |
| Assembly FFT | 0.85 ms |

An FFT is $O(N \log N)$, so halving $N$ from 512 to 256 cuts the work by roughly
$\frac{512 \times 9}{256 \times 8} = 2.25\times$.

**Write down** what you expect for each implementation at N = 256, and what percentage of a 20 ms
budget that is. Then run the lab and see how wrong you were. Being wrong on paper is the intended
experience — this course, like its predecessor, found every one of its own predictions optimistic.

### Step 2 — Run the benchmark

```python
--8<-- "src/labs/02-fft-test/02-fft-test.py"
```

The pure-Python pass is genuinely slow — expect to wait. That wait is itself the result.

### Step 3 — Check the cycle counter before trusting anything

The first line of output verifies the DWT counter is actually running, and at what rate. A value
near 150 MHz means timing on this board is trustworthy. A value of 0 means the counter is stalled
and no cycle-based number below it should be believed.

Verifying the instrument before reading it is not ceremony. It is the difference between a
measurement and a number.

### Step 4 — Read the verdict

The final table converts each mean into a percentage of the frame budget and applies the 50% rule.

## Expected Output

Approximate values for a Pico 2 at 150 MHz — **derived from the prerequisite course's published
512-point measurements**, not measured here. Your board is the authority:

```
Lab 2: FFT Test
N = 256 at 12800 Hz -> one frame is 20.0 ms of sound

DWT cycle counter: 149.87 MHz

captured 256 samples, peak 3.41% of full scale
mic readinto(): 20.02 ms per frame (expected ~20.0)

pure Python FFT : mean    62.41 ms   best    61.88 ms
assembly FFT    : mean     0.38 ms   best     0.37 ms

=== Verdict against a 20.0 ms frame budget ===
implementation    mean ms   % budget   real time?
--------------------------------------------------
pure Python         62.41      312.1%           NO
assembly             0.38        1.9%          YES

The assembly FFT fits 53x over inside one frame.
Lab 4's continuous pipeline is therefore comfortably possible.
```

## Interpreting the Result

Two conclusions come out of this, and the second is the one that matters.

**The pure-Python FFT misses the deadline by roughly 3×.** Not by a little. A wake-word detector
built on it would drop about two out of every three frames, and — this is the trap — it would
still *appear* to work. It would detect phrases sometimes. Its false-reject rate would look poor,
and you would spend a long time tuning a threshold when the actual problem was that most of the
audio never reached the detector at all.

**The assembly FFT uses about 2% of the budget.** That is the number that makes Lab 4 possible.
The remaining 98% is what pays for band energies, normalization, and template scoring, with room
left over.

!!! tip "This is why Lab 4 imports `fft_asm`"
    Lab 4 could import either implementation — the interfaces match. It imports the assembly one
    because of this measurement, not because assembly is inherently virtuous. Had the numbers come
    out differently, the honest response would have been to shrink the problem, not to press on
    and blame the detector.

!!! warning "If your board has no assembly FFT"
    Some MicroPython builds lack `@micropython.asm_thumb`. The lab reports that as a finding rather
    than crashing. On such a build, Lab 4 will drop frames and say so through its overrun counter.
    The honest fix is a faster FFT or a smaller problem — never a quietly relaxed budget.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `DWT cycle counter: 0.00 MHz` | Counter stalled | Timings are invalid; re-run, and do not trust cycle numbers |
| `mic readinto()` far from 20 ms | Wrong sample rate, or mic not streaming | Re-run Lab 1's microphone check |
| `assembly FFT: unavailable` | Build lacks `asm_thumb` | Expected on some builds; note it and continue |
| `peak 0.00% of full scale` | Microphone not delivering audio | L/R to GND; check SD wiring — see Lab 1 |
| Mean far above best | GC or interrupts firing inside the timed region | Expected variance; investigate if the gap exceeds ~10% |
| `MemoryError` during the Python FFT | Fragmented heap | Soft-reset the board and run this lab first |

## Challenges

1. **Score your prediction.** Compare what you wrote in Step 1 against what you measured. Which
   direction were you wrong in, and why?
2. **Find the crossover.** Run the benchmark at N = 128, 256, 512, and 1024. At each size the
   budget changes too — plot FFT time and budget on the same axes. Where does the pure-Python
   version stop being hopeless, and what did you give up in frequency resolution to get there?
3. **Delete the warm-up.** Remove the discarded first run and re-measure. How much does the mean
   move? Is the effect larger for the Python or the assembly version, and why?
4. **Move the `gc.collect()`.** Put it *inside* the timed region instead of before it. Explain the
   change in both the mean and the mean-to-best gap.
5. **Budget the whole pipeline.** Lab 4 adds band energies, normalization, and 480 float
   multiply-adds of template scoring per frame. Predict the total, then check your prediction
   against the worst-frame time Lab 4 reports on exit.

## Check Your Understanding

1. Where does the 20 ms budget come from? Derive it.
2. Why is `mic.readinto()` taking 20 ms a healthy result rather than a performance problem?
3. Why is the first FFT run discarded, and what would including it do to the mean?
4. An implementation uses 90% of the frame budget. Why is that a failure and not a pass?
5. A detector built on an FFT that misses the deadline still detects phrases sometimes. Why is
   that *more* dangerous than one that fails outright?

---

**Next:** [Lab 3: Microphone Calibration](../03-mic-calibration/index.md)  |  **Previous:** [Lab 1: Setup and Wiring](../01-setup/index.md)
