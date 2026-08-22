# TODO

Carried over from the 2026-08-21 calibration session.
Background and rationale: [`logs/calibration-session.md`](logs/calibration-session.md).

Current state: Lab 3 v1.7.0, `config.py` v2.3.0, working tree clean.
`SPEECH_FLOOR = FULL_SCALE * 0.00530` is measured and applied.

---

## P0 — Stale documentation (blocking for students)

The code moved from three buttons to two and from five modes to six; the prose
did not follow everywhere. A student reading these docs will be told to press a
button that no longer exists.

- [ ] **`docs/labs/03-mic-calibration/index.md`**
  - Line ~134: "**MODE** cycles the five tests, **UP** runs the current one,
    **DOWN** clears everything" → MODE cycles **six** modes, **SELECT** runs the
    current one, and **CLEAR** is now its own mode position.
  - Lines ~146/155/161: "Press **MODE**, then **UP**" → **SELECT** throughout.
  - Line ~80: still says the default is `0.0008` (≈58 dB SPL). It is now
    `0.00530`, measured in the basement shop. Update the number and say it was
    measured rather than guessed.
  - Document `calibration.json`, `ROOM_NOTE`, and `./get-results.sh`, none of
    which existed when that page was written.

- [ ] **`docs/labs/04-wake-word-test/index.md`**
  - Lines ~151–153: the control table still lists MODE/UP/DOWN with a two-mode
    LISTEN⇄ENROLL toggle. It is now **LISTEN → ENROLL → FORGET** with SELECT
    acting within each, and the threshold **wraps** (`0.99 → 0.30`) rather than
    stepping both ways.
  - Line ~199: "Change the threshold with **UP**/**DOWN**" → SELECT only, and
    explain the wrap.

- [ ] **`docs/labs/02-fft-test/index.md`** — no button references found; confirm
  it needs nothing.

---

## P1 — Correctness and verification

- [ ] **Run Lab 4 end to end on hardware with the measured `SPEECH_FLOOR`.**
  Never done. This is the first real test of `0.00530` against live speech, and
  the whole point of Lab 3.

- [ ] **Verify Labs 1 and 4 on the physical board.** Both were converted to two
  buttons *and* to IRQ+polling latching, but only ever exercised in the host
  stub harness. Lab 1's five checks and Lab 4's three modes have not been
  pressed by a human since the change.

- [ ] **Audit every lab for the flash-vs-I²S hazard.** Any code that writes a
  file while an `I2S` object is open will hard-fault the chip. Lab 3 is fixed;
  Lab 4 does not currently write files but would hit this the moment it saves a
  template. See [`memory: rp2-flash-i2s-hardfault`] and §1 of the session log.
  Consider a shared `config.save_json(path, data, mic)` helper that owns the
  deinit/reinit dance so no future lab can get it wrong.

- [x] **Fixed: `analyze-wake-words.py` reported every level 24 dB too low.**
  `GAIN` was 4 where it needed to be 64. `record-wake-words.py` writes
  `w >> (16 - GAIN_SHIFT)` while the 24-bit sample everything else quotes is
  `w >> 8`, so the file holds `sample24 >> 6`. The 4 is the gain relative to a
  straight 24-to-16 bit conversion, and that conversion has already divided by
  256 — two different numbers that look like the same one.

  Caught by cross-checking rather than by inspection: the takes' quiet frames
  put the room at 6,879 in 24-bit units and Lab 3 measured the same room at
  7,221 — 0.4 dB apart at 64, and 24.5 dB apart at 4. Every ratio the tool
  prints (the spectrum table, the sweep, `BAND_LO_HZ = 350`) is unaffected and
  was re-verified identical. What moved is every absolute level, which is
  exactly what a comparison against `SPEECH_FLOOR` depends on. The factor now
  lives in `wakeword_analysis.py` with its derivation and cross-check written
  down beside it.

- [x] **Fixed: the Explorer's listening filter was boosting, not cutting.**
  Web Audio takes `BiquadFilterNode.Q` for lowpass and highpass in **decibels**,
  so the reflexive `Q = 0.707` asks for a linear Q of 1.085 — a resonant filter
  that adds 1.7 dB just above the corner. Two cascaded made the takes 2 dB
  LOUDER through what was labeled a high-pass. Now a 4th-order Butterworth pair
  (Q = −5.33 dB and +2.32 dB), verified with `getFrequencyResponse()`.

- [ ] **Second clean NOISE run** to confirm the distribution shape is stable.
  One clean run said "acoustic transients" (`p75→p90` +1.5 dB, `p90→max`
  +3.4 dB). Worth one confirmation before treating it as settled.

---

## P2 — Wake Word Explorer (class deliverable)

- [x] **Build a Plotly dashboard called "Wake Word Explorer"** so students can
  look at their own recordings from `record-wake-words.py` rather than taking
  the numbers on faith. Seeing "Hey Pico" arrive as three energy bursts is what
  turns the 32-frame window and the 350 Hz band edge into consequences instead
  of settings someone handed them.

  - **Overview view:** all 10 takes at once as small horizontal waveform
    strips, stacked the way Audacity stacks tracks, with the FFT of each shown
    alongside its waveform.
  - **Drill-down:** selecting one take drops the dashboard to that file alone,
    at full width, with the same views enlarged.
  - **Controls along the top** to run analysis and filters across the takes.
    At minimum: a high-pass sweep, so the 350 Hz decision can be seen and heard
    rather than read off a table; a band-energy overlay using Lab 4's own 12
    log-spaced bands; the per-frame RMS envelope with the measured noise floor
    drawn in; and a spectrogram.

  `src/tools/analyze-wake-words.py` already computes the envelope, the phrase
  extent, and the band spectrum. The dashboard should share that math rather
  than re-implement it, so the printed numbers and the plotted ones cannot
  drift apart. The sample takes live in `docs/sounds/` -- inside `docs/` so the
  dashboard can fetch them over the same web server that serves the book -- and
  are committed on purpose: the dashboard needs real data on first run, before
  a student has recorded anything of their own.

  **Done.** Built at `docs/dashboards/wake-word-explorer/`, in the nav under
  Dashboards. All four control requirements are in: a `BAND_LO_HZ` sweep over
  16 stops that also filters playback, the 12 log-spaced bands drawn as
  spectrogram axis ticks and edge lines, both RMS envelopes against the noise
  floor and `SPEECH_FLOOR`, and a spectrogram. The overview stacks all ten
  takes Audacity-style with each take's FFT beside it; clicking a strip drills
  down to that take full width.

  The shared-math requirement is met by extracting
  `src/tools/wakeword_analysis.py`, which `analyze-wake-words.py` now imports
  (verified byte-identical output before and after the refactor) and which
  `build-explorer-data.py` uses to generate the dashboard's data file. The
  browser only ever SUMS a spectrogram Python computed; Python ships a checksum
  of every one of those sums, and the console reports agreement to 0.02 dB.
  `src/tools/test_explorer_data.py` checks the same thing host-side — worst
  error across all takes and cutoffs is 0.0023 dB.

  Rebuild after re-recording with `python3 src/tools/build-explorer-data.py`.
  Two real bugs fell out of building this; both are recorded under P1.

---

## P3 — The real detector improvement

This is the most valuable open item and came directly out of the measured data.

- [ ] **Gate on band-limited energy, not broadband RMS.**
  `feature_frame()` in Lab 4 computes `rms` from raw time-domain samples, but
  the 12 feature bands span only 150–6000 Hz. **76% of this room's noise power
  sits below 400 Hz** (furnace fan), so `SPEECH_FLOOR` is being set almost
  entirely by energy the detector never looks at.
  Computing the gate from the summed band energies instead should drop the
  noise term by ~6 dB at far smaller cost to speech, and would likely lift the
  recommendation off the `capped-at-0.7x-speech` clamp it is stuck on today.

  **Now measured, and better than the estimate.** The Explorer computes both
  gates over the ten takes: at the peak of the phrase they are **0.3 dB**
  apart, and on the quiet frames between words they are **15.1 dB** apart
  (broadband 6,621, band-limited 1,163). The room therefore drops from 16.5 dB
  below `SPEECH_FLOOR` to 31.6 dB below it at essentially no cost to speech —
  15 dB, not 6. Lab 4 v1.6.0 in the working tree already makes this change; the
  remaining work is re-measuring `SPEECH_FLOOR` against the new gate.

- [ ] **Add a speech-spectrum pass to Lab 3.** Lab 3 measures a *noise*
  spectrum only, so how much speech energy lives below 400 Hz is unknown and
  the optimal `BAND_LO_HZ` is currently a guess. A SPEECH-SPECTRUM mode would
  make it a measurement. Prerequisite for choosing `BAND_LO_HZ` honestly.

- [ ] **Re-measure `SPEECH_FLOOR` after any `BAND_LO_HZ` change.** The two
  interact: raising `BAND_LO_HZ` changes what the gate should be. Do not tune
  them independently.

- [ ] **Try the mic at ~8 inches.** Halving distance buys ~6 dB of SNR
  directly. The clip test showed the loudest sample at only **9.7% of full
  scale**, so there is ~20 dB of unused range. This may clear the
  `capped-at-0.7x-speech` clamp on its own, without any code change — worth
  testing before writing code.

---

## P4 — Workflow and usability

- [ ] **Load `calibration.json` at startup in Lab 3** so measurements
  accumulate across runs. Today NOISE and SPEECH must happen in a single
  session; restarting resets them to `None` and the next save overwrites the
  file. This bit us repeatedly.

- [ ] **Decide where the diagnostic programs live.** `00-button-probe.py`,
  `00-mic-throughput.py`, and `02-button-test.py` are debugging tools, not
  labs, but they sit in the lab numbering and upload with it. Either move them
  to `src/diagnostics/` (and teach `upload-code.sh` about it) or document them
  as intentional troubleshooting aids. `00-button-probe.py` in particular was
  written for one specific dead end and may not be worth keeping.

- [ ] **Decide whether `src/labs/results/` belongs in git.** Not currently
  ignored. `calibration.json` is real measured data worth keeping;
  `partial.json` is the recovered fragment from the contaminated run and is
  probably not.

---

## P5 — Nice to have

- [ ] **Extend `analyze-calibration.py`** to compare two calibration files, so
  "mic at 15 in" vs "mic at 8 in" is a diff rather than two printouts read side
  by side.

- [ ] **Record fan state with every measurement.** The furnace cycles, so two
  runs of "the same room" are not comparable across fan states. A `FAN_RUNNING`
  flag next to `ROOM_NOTE`, written into the JSON, would make this explicit.

- [ ] **Consider raising `MEASURE_MS` for NOISE.** Five seconds is 250 frames;
  the p99 statistic rests on ~2 frames. A longer noise measurement would make
  the tail estimate meaningfully more stable, and nothing about this lab is
  time-critical.

---

## Notes for whoever picks this up

- **The `mpremote` workflow beats Thonny here.** `mpremote connect <port> run
  <file>` streams output to the terminal and releases the port on a *single*
  Ctrl-C. Thonny holds the port even after STOP, which blocks every upload.
- **Repeated Ctrl-C wedges the port.** It kills mpremote inside
  `serial.close()`. One Ctrl-C, then wait.
- **A board that enumerates but gives no REPL has hard-faulted.** It will not
  come back from `mpremote reset` — pull the USB cable.
- **If an input appears not to work, script the input** before rewriting the
  input handling. Patching `config.latch_buttons` to auto-fire presses is what
  finally cracked this session's bug, after two hours of fixing buttons that
  were never broken.
