# Lab 3 Calibration Session Log

**Date:** 2026-08-21
**Board:** Raspberry Pi Pico 2, serial `961aca2a7f3302cd`, `/dev/cu.usbmodem101`
**Room:** basement shop, furnace fan running, mic 15 in (38 cm) from speaker, mounted above the OLED over the Pico

**Goal at the start:** fix `upload-code.sh` after some files moved.
**Goal by the end:** find out why the MODE button did nothing, and produce a measured `SPEECH_FLOOR`.

Both were achieved. The middle took far longer than it should have, for reasons documented here.

---

## 1. Executive summary

The session's dominant bug had nothing to do with buttons, despite presenting as a dead button and consuming roughly four rounds of button-focused fixes.

**Root cause:** `save_results()` in Lab 3 wrote `calibration.json` to flash while the I²S microphone stream was still open. On the RP2, programming flash disables execute-in-place (XIP); the I²S DMA completion interrupt's handler lives in flash; when that interrupt fired inside the write window the CPU jumped to code it could not fetch and **hard-faulted the chip**.

The failure had no Python-visible symptom: no exception, no traceback, no output. The board simply stopped, and stayed stopped through both `mpremote soft-reset` and `mpremote reset` — it needed the USB cable pulled.

**Observed symptom:** "I press SELECT and NOISE runs. I press MODE and nothing happens."
**Actual situation:** the board was already dead by the time MODE was pressed. SELECT only ever appeared to work because it was pressed *before* the first measurement.

**Fix:** `mic.deinit()` before the write, reopen in a `finally`. Shipped as Lab 3 v1.7.0.

Along the way five genuine secondary bugs were found and fixed, and two of my own analysis tools were found to be wrong.

---

## 1a. Elapsed time

Derived from git commit times and file modification times, not from conversation
timestamps — so this is wall-clock elapsed time for the whole working session,
including thinking, physical button pressing, and the several minutes lost to
unplugging a hard-faulted board. It is not "time spent typing".

| Time | Milestone | Gap |
|---|---|---|
| 10:11:28 | `ef5c9fc` "new labs" — earliest activity today | — |
| 11:00:40 | `4d42b94` upload script, JSON output, `--clean` | +49 min |
| 11:26:18 | `497cf62` two-button conversion | +26 min |
| 13:24:04 | `f023d56` button test written, "found another bug" | **+118 min** |
| 14:13:42 | `04db256` isolating the hang after the flash write | +50 min |
| 14:56:38 | `e74d795` fixed by closing the mic before writing | +43 min |
| 14:57:39 | session log written | +1 min |

**Total elapsed: 4 h 46 min.**

**Time on the MODE-button bug (11:26 → 14:14): 2 h 47 min — 58% of the entire
session.** Of that, roughly the first two hours went to fixing button handling
that was never broken; the actual root cause was found and fixed in the last
45 minutes, once the input was scripted rather than pressed.

The single largest gap in the table, +118 minutes, is the stretch covering
rounds 1–4 of the hypothesis table in §7: IRQ latching, dual IRQ-plus-polling,
`02-button-test.py`, and `00-button-probe.py`. Every one of those changes was
correct in isolation and none of them addressed the failure.

For calibration: the productive non-bug work — upload script repair, JSON
output, `--clean`, port discovery, the full two-button conversion across four
labs and two documents — took **75 minutes** in total.

---

## 2. Timeline

### Phase 1 — Upload script repair
- Files had been flattened: `src/labs/NN-*.py`, `src/labs/lib/*.py`, `upload-code.sh` alongside.
- `upload-code.sh` still globbed `labs/*/[0-9]*.py` (matched nothing) and looked for `config.py` in the wrong place. Fixed to `[0-9]*.py` and a sibling `config.py`.
- Added warnings for missing libs/config rather than silent skips.

### Phase 2 — First calibration data
- Seven NOISE runs: median ~6,600–7,500, worst 15,769–20,907.
- Established the shipped `SPEECH_FLOOR = FULL_SCALE * 0.0008` (= 6,711) sat **below** the median of an empty room (~7,000) — the gate was effectively wide open.
- Noted a reproducible ~9 dB gap between median and worst frame. **This became the thread I pulled on for far too long.**

### Phase 3 — Lab 3 instrumentation
- Added explicit console instructions and per-mode help.
- Added `calibration.json` output written after every measurement.
- Added percentile capture (p10/p25/p50/p75/p90/p99/max) specifically to distinguish *periodic* contamination from *isolated* transients.
- Added `get-results.sh` to fetch results.

### Phase 4 — Device hygiene
- Discovered a stale `main.py` on the device (a copy of `56-fft-asm.py` from the prerequisite course) that MicroPython auto-runs at boot.
- Added `--clean` to `upload-code.sh`: rescues `calibration.json`, lists the device, requires typing `DELETE`, then wipes and re-uploads. Wipe walks the filesystem on-device because mpremote 1.24 has no `rm -r`.

### Phase 5 — "Three duplicate devices"
- User reported three devices. There was one.
- macOS exposes every serial port twice (`/dev/cu.X` and `/dev/tty.X`), plus always-present `cu.Bluetooth-Incoming-Port` and `cu.debug-console`.
- My glob matched both the `cu` and `tty` twins, so one Pico printed a "Multiple serial devices found" warning — I had manufactured the confusion.
- Fixed by asking `mpremote connect list` and filtering on USB VID:PID (`0000:0000` = not a real board). Factored into `find-port.sh`, shared by both scripts.

### Phase 6 — Two buttons, not three
- Hardware actually has two momentary switches, on GPIO 14 and 15. `config.py` assumed three (13/14/15).
- Agreed scheme: **MODE cycles state, SELECT acts within it.** Adjustable values *wrap* (volume `0…10→0`, threshold `0.70…0.99→0.30`). Destructive actions get their own mode position (Lab 3 `CLEAR`, Lab 4 `FORGET`) so a stray press cannot fire them.
- Applied across `config.py`, Labs 1/3/4, `src/README.md`, and `docs/labs/01-setup/index.md`.

### Phase 7 — The button investigation (the long one)

| Round | Hypothesis | Change | Result |
|---|---|---|---|
| 1 | Press lost during the ~8 s blocking measurement | IRQ latch (v1.5.0) | No change |
| 2 | GPIO 14's interrupt not firing | IRQ **and** polling, polled inside measurement loops (v1.6.0) | No change |
| 3 | Wiring | Wrote `02-button-test.py` | GPIO 14 works perfectly |
| 4 | Opening I²S kills GPIO 14 | Wrote `00-button-probe.py` (two-phase, mic off vs on) | 5 clean edges in **both** phases |
| 5 | Flash write vs I²S DMA | Isolated flash-write test | **Survived** — wrong again |
| 6 | The loop isn't running at all | Scripted the button press to remove the human | **Reproduced. Loop never resumes.** |
| 7 | Where exactly? | Source-level marker injection | `[t] pre-save` printed, `[t] post-save` never did |

Round 6 was the breakthrough: patching `config.latch_buttons` to auto-fire a SELECT and then a MODE press reproduced the failure with no human involved, and immediately proved the MODE press was never even *evaluated*.

### Phase 8 — Fix and verification
- v1.7.0: `mic.deinit()` around the flash write, reopen in `finally`.
- Verified on hardware with the scripted-press harness:
  ```
  [t] pre-save
  [t] POST-SAVE  <-- survived the flash write
  [t] auto-press mode
  >>> Mode 2/6: SPEECH
  [t] loop still alive after 401 polls
  ```
- User then completed a full five-mode run successfully.

---

## 3. Errors I made

### 3.1 Chased a hypothesis for six rounds on no evidence
I fixated on the OLED's SPI traffic as the source of the loud "quiet room" frames, because `collect()` calls `oled.show()` every 8th frame (12.5% of frames) and the mic sits physically above the display. I built a whole percentile-analysis apparatus around distinguishing "periodic" from "transient", and wrote the periodic verdict text to name the display specifically.

**The final clean data refuted it outright**: `p75→p90` is +1.5 dB while `p90→max` is +3.4 dB — a tight body with a few outliers, i.e. acoustic transients. The earlier wide spreads were the stale mic buffer carrying the button click.

The percentile work was still worth having — it is what *settled* the question — but I presented the display theory with more confidence than the evidence supported, repeatedly.

### 3.2 Missed the single clearest signal in the session
MODE produced **no console output whatsoever**. A missed button edge does not do that — the loop keeps running and the *other* button keeps working. "No output at all" means the program stopped executing. That distinction was available from the first report and should have redirected me immediately to "is the loop alive?" instead of "is the press detected?".

### 3.3 Explained away the actual smoking gun
I found `calibration.json` at 0 bytes beside an orphaned 771-byte `calibration.json.tmp` and concluded it was an interrupted STOP. It was a write killed mid-flight by the hard fault. I even *used* it as supporting evidence for the crash-safe-write feature rather than asking what kills a program during a flash write.

### 3.4 Built a diagnostic before doing the reasoning
`02-button-test.py` was written to rule out wiring that was never in question — SELECT demonstrably worked, so the buttons, the pull-ups, and the GND return were all proven. The reasoning ("what could make the loop stop?") was cheaper than the program and would have got there faster.

### 3.5 Two bugs in my own analysis tool
- **Bin-count weighting.** `analyze-calibration.py` summed per-band *mean power per bin* to compute low-frequency share. The bands are log-spaced — the top band spans 31 bins, the bottom spans 1 — so this badly overstated the low end. Reported **89% below 400 Hz**; the true bin-count-weighted figure is **76%**.
- **dB arithmetic.** After fixing the above I divided the result by 2, reporting a 3.1 dB noise reduction where the correct figure is 6.1 dB. Removing a power fraction `f` leaves amplitude `sqrt(1-f)`, so the RMS drop is `-10·log10(1-f)` — already in amplitude dB. Caught by cross-checking the tool against a direct computation.

Both were caught only because I checked the tool against an independent calculation. Neither was caught by it "looking right".

### 3.6 Told the user the right thing for the wrong reason
I advised waiting a beat after RESULT before pressing STOP, attributing lost data to an interrupted write. The real cause was the hard fault. Good advice, wrong model — and the wrong model is what kept me from the real bug.

### 3.7 Self-inflicted port contention
Several times I killed `mpremote` and immediately retried, racing my own cleanup. Worse, I left a **background polling loop** running that held the port, then spent two rounds diagnosing "the device won't respond" when the cause was my own process. Once I suggested the user reset the board while my process was the thing blocking it.

### 3.8 Test-harness bugs that cost real time
- A pty feeder that returned `"no\n"` on every read instead of once, flooding the terminal with ~20,000 characters.
- A driver that advanced its sequencer from `ticks_ms()`; when I rewrote Lab 3's loop to stop calling it, the test hung for the full 120 s timeout.
- A heredoc collision: an inner `<<'PYEOF'` inside an outer `<<'PYEOF'` terminated the outer one early, producing a shell parse error.
- Called a helper with a 2-tuple where it expected a 3-tuple, aborting a patch mid-run.
- Left a stray `''` on a `ROOM_NOTE` assignment (valid Python, unintended).

### 3.9 Premature guarantee
I documented "an interrupted session still leaves usable data on the Pico" in the lab banner **before** the write was actually crash-safe. The very next run produced a 0-byte file, contradicting text I had already shipped.

---

## 4. Errors and misreadings on the user's side

Recorded factually, because they shaped the investigation.

### 4.1 Incomplete measurement runs
The first several sessions ran only mode 0 (NOISE), sometimes repeatedly, and once pressed DOWN (clearing all measurements) mid-session. `recommend()` requires **both** NOISE and SPEECH, so no recommendation could be produced. In fairness, this was partly caused by the bug — the board was dead, so advancing to SPEECH was impossible.

### 4.2 The keyboard hypothesis — raised, then correctly retracted
User reported typing on a keyboard 6 in from the mic and pressing the button under the mic. I concluded the typing contaminated the measurement. User then clarified: **the progress bar had already filled** before typing began. That correction was right and mine was wrong — and it was a useful redirect, because it eliminated a plausible-sounding explanation that would have masked the real one.

### 4.3 "Three duplicate devices"
Three device nodes, one board. Reasonable misreading of macOS `cu`/`tty` twins plus built-in pseudo-ports — and my script's spurious "Multiple serial devices found" warning actively encouraged it.

### 4.4 Repeated Ctrl-C wedging the port
`^C^C^C^C` on `mpremote run` killed it during `serial.close()`, leaving the port locked and stalling subsequent uploads. One Ctrl-C, then let it exit.

### 4.5 Hardware spec discovered mid-flight
`config.py` described three buttons; the hardware has two. Not an error so much as a late discovery, but it meant a full pass over four files and two docs partway through an unrelated investigation.

---

## 5. What worked

### 5.1 Host-side stub harness
Stubs for `machine`, `ssd1306`, `micropython`, and `fft_asm` let the MicroPython labs run on CPython. A generic driver scripted button presses and ran a whole lab end to end in under a second. This caught real bugs before they ever reached hardware and made every fix testable.

### 5.2 Fault injection
The harness grew switches to simulate specific faults:
- `IRQ_DEAD_PINS=14` — simulate an interrupt that never fires
- `PRESS_ON_FRAME=100` — press a button mid-measurement
- `FAIL_DUMP_AFTER=0` — make `json.dump` fail mid-write

Each verified a fix against the actual failure mode rather than the happy path. The `FAIL_DUMP_AFTER` test proved the previous good result survived a failed write byte-identically.

### 5.3 Scripting the human out of the loop
The decisive move. Patching `config.latch_buttons` to auto-fire presses turned an intermittent, human-paced, hardware-dependent bug into a deterministic 25-second reproduction — and instantly showed that the MODE press was never evaluated.

**If an input appears not to work, script the input.** It separates "the input was not detected" from "the code that would handle it never ran".

### 5.4 Marker injection to localize
Rather than guessing which line hung, I string-replaced markers into the lab's source before `exec()`. `[t] pre-save` printing and `[t] post-save` not printing localized the hang to one function call in a single run.

### 5.5 Two-phase controlled probe
`00-button-probe.py` ran the identical watch loop twice, with the microphone as the **only** difference, and printed raw pin transitions plus an "...alive" heartbeat so a dead pin could not be confused with a dead program. It cleanly exonerated the mic — a negative result that mattered.

### 5.6 Version stamping (user's idea)
Every program now prints `NAME vX.Y.Z (config vA.B.C)` on its first line, and `calibration.json` records all three. This removed all ambiguity about which build produced which output — genuinely valuable in a session with seven Lab 3 revisions.

### 5.7 Crash-safe writes that actually paid off
Writing to `.tmp` then renaming meant the hard fault destroyed only the temp file. The recovered 771-byte `.tmp` turned out to be complete JSON from the contaminated run, and supplied the percentiles that first suggested "transient, not periodic".

### 5.8 Validation on the read side
`get-results.sh` learned to reject empty/truncated JSON and print a summary. It caught the real 0-byte file immediately instead of reporting a successful fetch of nothing.

---

## 6. Secondary bugs found and fixed

| # | Bug | Impact | Fix |
|---|---|---|---|
| 1 | `countdown()` discarded one 20 ms frame from a **781 ms** mic buffer | Up to 761 ms of stale audio — including the button click — measured as room noise. Produced a 157,732 worst-frame (27.8 dB above median) | Drain the whole buffer (43 frames) |
| 2 | Same bug in Lab 4's `enroll()` | Every enrolled template had the button click baked into its front | Same drain |
| 3 | `save_results()` opened the target file directly | `open(path,"w")` truncates immediately; any interruption destroyed the previous result | Write `.tmp`, then rename |
| 4 | Button presses lost during blocking work | A press starting and ending inside an 8 s measurement produced no observable edge | IRQ latch + polling inside measurement loops |
| 5 | `get-results.sh` conflated "file missing" with "port busy" | Told the user to run the lab they had just run | Keep mpremote's stderr, branch on it |
| 6 | `upload-code.sh` globbed `cu.*` and `tty.*` twins | One board reported as "multiple devices" | Filter via `mpremote connect list` on VID:PID |
| 7 | `mpremote ls \| sed` under `set -o pipefail` | A failed listing killed the script with an unrelated message | Capture output, branch explicitly |

---

## 7. Final state

### Versions on device
| File | Version |
|---|---|
| `config.py` | **2.3.0** |
| `00-button-probe.py` | 1.0.0 |
| `00-mic-throughput.py` | 1.0.0 |
| `01-setup.py` | 1.3.0 |
| `02-button-test.py` | 2.0.0 |
| `02-fft-test.py` | 1.0.0 |
| `03-mic-calibration.py` | **1.7.0** |
| `04-wake-word-test.py` | 1.3.0 |

### Measured calibration (v1.7.0, clean run, fan running, 15 in)
Timing verified: 5006 ms of an expected 5000 ms, 256/256 samples per frame — no short reads.

| | frame RMS | dBFS | ~dB SPL |
|---|---|---|---|
| noise median | 7,221 | −61.3 | 59 |
| noise p75 | 9,994 | | |
| noise p90 | 11,941 | | |
| noise worst | 17,675 | −53.5 | 66 |
| speech top decile | 63,461 | −42.4 | 78 |
| speech peak | 95,363 | −38.9 | |
| **SNR** | | | **18.9 dB** |

- **Distribution:** `p75→p90` +1.5 dB, `p90→max` +3.4 dB → acoustic transients, **not** periodic contamination.
- **Headroom:** loudest sample 9.7% of full scale — roughly 20 dB unused.
- **Noise spectrum** (bin-count weighted): 35% below 250 Hz, **76% below 400 Hz**, 84% below 500 Hz. Loudest band 150–200 Hz — the furnace fan.
- **Applied:** `SPEECH_FLOOR = FULL_SCALE * 0.00530`, set by the `capped-at-0.7x-speech` rule (was `0.00080`, below the median empty room).

---

## 8. Open questions

1. **The gate is broadband; the features are not.** `feature_frame()` computes `rms` from raw time-domain samples, but the 12 bands span only 150–6000 Hz. With 76% of noise power below 400 Hz, `SPEECH_FLOOR` is set almost entirely by energy the detector never examines. Gating on band-limited energy instead should drop the noise term ~6 dB at much smaller cost to speech.

2. **How much speech lives below 400 Hz?** Unknown — Lab 3 measures a *noise* spectrum only. Adding a speech-spectrum pass would make the optimal `BAND_LO_HZ` a measurement rather than a guess.

3. **The `capped-at-0.7x-speech` clamp is binding**, meaning no clean separation exists in this room at 15 in. Moving the mic to ~8 in buys ~6 dB directly and would likely clear it. The 9.7% headroom figure says there is ample room to do so.

4. **Cross-session accumulation.** Measurements live in RAM, so NOISE and SPEECH must happen in one run; a restart resets them and the next save overwrites the file. Loading `calibration.json` at startup would make the modes independent.

---

## 9. Lessons

1. **"No output at all" is a different symptom from "input not detected."** The first means the program stopped; the second means it is running and missed something. Distinguish these before touching input code.

2. **A dismissed anomaly is usually the bug.** The 0-byte file beside a live `.tmp` was the fault signature, seen and explained away early.

3. **Script the input.** Removing the human turned an intermittent hardware-dependent bug into a deterministic 25-second reproduction.

4. **Verify tools against independent arithmetic.** Both analyzer bugs produced plausible, well-formatted, wrong numbers. Neither would have been caught by inspection.

5. **On the RP2, never write flash while an I²S stream is open.** Deinit around the write. The failure mode gives no Python-visible evidence and needs a physical power cycle.

6. **Confidence should track evidence.** The display-chatter theory was stated repeatedly as a leading candidate on the strength of a coincidence (12.5% redraw rate vs an elevated p90) and was ultimately wrong.
