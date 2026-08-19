# Smart Speaker Kit — Proof of Concept

Four programs that prove the hardware for this course actually works, in the
order you should run them. **Everything here runs on a plain Pico 2** — no
Wi-Fi, no cloud account, no API keys. The Pico 2 W's radio is not touched until
the networking labs later in the course.

| Lab | Question it answers |
|---|---|
| [01-setup](labs/01-setup/) | Is every peripheral wired correctly? |
| [02-fft-test](labs/02-fft-test/) | Can this chip do the DSP in real time? |
| [03-mic-calibration](labs/03-mic-calibration/) | How loud is my room, and how loud am I? |
| [04-wake-word-test](labs/04-wake-word-test/) | Can it detect a phrase in a live audio stream? |

## Wiring

Pin assignments live in exactly one place — [`config.py`](config.py). Nothing
else in the kit knows a pin number, so re-wiring means editing one file.

**Display — SSD1306 128×64 OLED (SPI0)**

| OLED pin | Pico GPIO |
|---|---|
| SCL / CLK | 2 |
| SDA / MOSI | 3 |
| RES | 4 |
| DC | 5 |
| CS | 6 |

**Microphone — INMP441 I²S MEMS (I2S peripheral 0, RX)**

| INMP441 pin | Pico GPIO |
|---|---|
| SCK | 10 |
| WS | 11 |
| SD | 12 |
| L/R | GND (left channel) |

**Buttons — three momentary push buttons**

| Button | Pico GPIO | Role |
|---|---|---|
| MODE | 13 | Cycle the program's state |
| UP | 14 | Volume up / threshold up / record enrollment |
| DOWN | 15 | Volume down / threshold down / forget enrollments |

Each button's other leg goes to **GND**. `PULL_UP` holds the pin at 1, so a
press is a **falling** edge — the detail that trips up most people first time.

**Speaker — MAX98357A I²S class-D amplifier (I2S peripheral 1, TX)**

| MAX98357A pin | Pico GPIO |
|---|---|
| BCLK | 16 |
| LRC | 17 |
| DIN | 18 |
| SD (shutdown) | 19 *(optional — leave unconnected for default gain)* |

The amplifier's own `SD` pin is a shutdown input. Wiring it to a GPIO lets
software cut the amplifier dead, which is the hardware half of the
mute-and-resume self-trigger mitigation the course builds later.

The RP2350 has **two** I²S peripherals, which is why the microphone and the
speaker can both be I²S and still run independently, at different sample rates.

## Uploading

```bash
./upload-code.sh
```

Quit or disconnect Thonny first — only one program can use the Pico's serial
port at a time.

Files land flat on the device (`config.py`, `lib/*.py`, and each lab as
`NN-name.py`), so from the REPL each lab is just:

```python
import importlib; importlib.import_module("01-setup")
```

or simply open the file in Thonny and press Run.

## Lab 1 — Setup

Steps through five checks: LED, display, buttons, microphone, speaker. Press
**MODE** to advance. In the speaker check, **UP**/**DOWN** change the volume.

Run this first and run it again whenever anything downstream behaves oddly. Its
whole purpose is that when Lab 4 fails to hear a wake word, you already know the
microphone is fine and can go looking for the bug somewhere useful.

## Lab 2 — FFT Test

Measures how much of one audio frame's time budget an FFT actually consumes.
The budget is not a matter of opinion: at 12800 Hz, 256 samples **is** 20 ms of
sound. If the FFT takes longer than that, the next frame arrives while you are
still working on the last one, and it is gone.

It benchmarks the pure-Python FFT and the assembly FFT — both taken from the
prerequisite course, [Real-Time DSP on a $5
Microcontroller](https://dmccreary.github.io/fft-benchmarking/) — against that
budget, and prints a verdict for each.

Expect the pure-Python FFT to blow the budget and the assembly FFT to fit inside
it many times over. That gap is exactly why Lab 4 uses the assembly version.

## Lab 3 — Microphone Calibration

Measures your room's noise floor and your own speaking level, then computes
`SPEECH_FLOOR` — the loudness gate Lab 4 uses so that silence cannot match
silence. **Run this before Lab 4.** The value in `config.py` is a guess about a
generic quiet room; this replaces it with a measurement of yours.

Five modes: NOISE, SPEECH, CLIP, SPECTRUM, RESULT. MODE cycles, UP runs the
current test, DOWN clears. It prints a line to paste into `config.py`.

Also reports your signal-to-noise ratio. Under about 15 dB is a hard room, and
the fix is physical — halving your distance to the mic buys ~6 dB, which beats
any amount of threshold tuning.

## Lab 4 — Wake Word Test

The point of the kit, at its smallest honest size. The microphone streams
without stopping; every 20 ms frame becomes a spectrum; a rolling 800 ms window
of those spectra is compared against a phrase you enrolled yourself. The reference phrase for
this course is **"Hey Pico"**.

**Controls**

| Button | In LISTEN | In ENROLL |
|---|---|---|
| MODE | switch to ENROLL | switch to LISTEN |
| UP | raise threshold (stricter) | record one repetition |
| DOWN | lower threshold (looser) | forget all enrollments |

**To use it:** press MODE to reach ENROLL, then press UP and say "Hey Pico"
after the countdown. Do that three to five times **at a consistent pace** — the
display reports window fill after each take, and you want 85–99%. Press MODE to
return to LISTEN and say the phrase.

Pace matters far more than volume here: the features are loudness-normalized, so
speaking louder changes nothing, while speaking faster than you enrolled drops
the score sharply. See the [Lab 4 writeup](../docs/labs/04-wake-word-test/index.md)
for the measured fill-versus-score table behind the 0.70 default threshold.

**How it works** — template correlation, not a neural network:

1. Read 256 samples (20 ms). This never stops.
2. Window, FFT, collapse 128 bins into 12 log-spaced band energies.
3. Subtract the frame's mean log-energy, then normalize to unit length.
4. Push into a ring buffer of the last 40 frames (800 ms).
5. Score against the template: the mean dot product, frame by frame. Both
   vectors are unit length, so a perfect match scores 1.0.
6. Above threshold **and** loud enough to be speech → wake.

Step 3 is the one that looks skippable and is not. Raw log band energies for
ordinary speech all land within a few percent of each other, so without
mean-subtraction every normalized vector points nearly the same direction and
*everything* scores about 1.00 — silence included. Removing the common offset is
what leaves only the spectral **shape**, which is the part that identifies a
phrase. Real MFCC pipelines do the same thing under the name cepstral mean
normalization.

**What it measures about itself.** On exit it reports the worst per-frame
processing time and a count of frame overruns. An overrun means audio was
dropped, which means any accuracy number from that run is partly a timing
artifact. Fix the budget before trusting the accuracy.

**Honest limits.** Template correlation is genuinely worse than a trained
keyword-spotting model, and single-speaker enrollment generalizes poorly to
other voices. It earns its place here by using nothing you have not already
built, needing no training toolchain, and having no step you cannot inspect.
Measuring how much worse it is than a trained model is a course exercise, not a
flaw to hide.

## Verifying the detector math without hardware

```bash
python3 tools/test_detector_math.py
```

Imports the real Lab 4 detector, stubs the hardware, and drives it with synthetic
speech. Every number in the Lab 4 writeup comes from this. Run it after any change
to feature extraction or scoring — if every row scores ~1.00, the mean-subtraction
step has been lost and the detector has no discriminative power.

## Vendored files

`lib/` contains four files copied unmodified from the prerequisite course's
repository:

| File | Origin | Purpose |
|---|---|---|
| `ssd1306.py` | `src/kits/fft-lab-kit/lib/` | OLED driver |
| `fftlab.py` | `src/kits/fft-lab-kit/lib/` | Pure-Python FFT |
| `fft_asm.py` | `src/fft-benchmark/device/` | ARM assembly FFT |
| `dwt_timer.py` | `src/fft-benchmark/device/` | Cycle-accurate timing |

They are vendored rather than referenced so this repo runs standalone.
