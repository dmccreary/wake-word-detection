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

- [ ] **Second clean NOISE run** to confirm the distribution shape is stable.
  One clean run said "acoustic transients" (`p75→p90` +1.5 dB, `p90→max`
  +3.4 dB). Worth one confirmation before treating it as settled.

---

## P2 — The real detector improvement

This is the most valuable open item and came directly out of the measured data.

- [ ] **Gate on band-limited energy, not broadband RMS.**
  `feature_frame()` in Lab 4 computes `rms` from raw time-domain samples, but
  the 12 feature bands span only 150–6000 Hz. **76% of this room's noise power
  sits below 400 Hz** (furnace fan), so `SPEECH_FLOOR` is being set almost
  entirely by energy the detector never looks at.
  Computing the gate from the summed band energies instead should drop the
  noise term by ~6 dB at far smaller cost to speech, and would likely lift the
  recommendation off the `capped-at-0.7x-speech` clamp it is stuck on today.

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

## P3 — Workflow and usability

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

## P4 — Nice to have

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
