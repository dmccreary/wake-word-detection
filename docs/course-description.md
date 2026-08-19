---
title: Course Description
description: A hands-on follow-on course that turns a bare wake-word detector into a cloud-connected smart speaker on a Pico 2 W
quality_score: 100
---

# Course Description

- **Title:** Smart Speakers on a $7 Microcontroller — From Wake Word to Working Voice Assistant
- **Course Length:** 8 weeks, or self-paced independent study
- **Audience:** Students who have completed *Real-Time DSP on a $5 Microcontroller* (or have equivalent experience) and want to turn a wake-word detector into a working assistant
- **Format:** Hands-on across two tracks that meet at a network boundary — 25 laboratory exercises split between the Pico 2 W and a small backend service the student writes and deploys

## Summary

This course starts exactly where its prerequisite course stopped on purpose. *Real-Time DSP on a
$5 Microcontroller* ends its optional Chapter 28 by building a wake-word detector and then drawing
a hard line: everything past "yes, that was the trigger phrase" — transcription, understanding
what was asked, answering out loud, not re-triggering on your own voice, remembering what was just
said — is "an entire second project." This course *is* that project.

You will take a working wake-word detector on a Raspberry Pi Pico 2 W and build everything after
the trigger: getting the board onto Wi-Fi without starving the microphone, shipping buffered audio
to a cloud speech-to-text endpoint, turning a raw transcript into a structured command, calling a
cloud text-to-speech endpoint and playing the result through a speaker, keeping the speaker's own
voice from re-triggering the microphone, carrying short-term conversation state across a follow-up
question, and standing up the backend service — with authentication, logging, and rate limiting —
that the board talks to. By the end you will have a genuine, narrowly-scoped smart speaker: one
trigger phrase, one or two skills, measured honestly for both accuracy and latency, with every
design compromise stated rather than hidden.

## Why This Course Exists

A wake-word detector is a yes/no classifier. A voice assistant is a distributed system: an
always-on embedded client, a network link that can drop at the worst moment, a cloud speech
pipeline, an intent layer that has to decide what you meant, a spoken response that has to not
confuse the microphone that is still listening, and a backend that has to not fall over or leak an
API key. None of that is "more FFT." It is a different discipline, and most hobbyist wake-word
projects stop at the detector precisely because what comes after is unglamorous, cross-cutting, and
easy to get wrong quietly — a conversation that silently loses context, a device that interrupts
itself, a backend with no rate limit that burns through a cloud budget in an afternoon.

**This is the deliberately unglamorous half of "build a smart speaker," made concrete and
measurable.** Commercial assistants target end-to-end wake-to-spoken-response latency in the
low single-digit seconds and treat that number as a product requirement, not a nice-to-have. This
course adopts the same discipline the prerequisite course used for FFT benchmarking — predict a
number, measure it on your own hardware, and explain the gap — and points it at latency, false
accepts *during playback*, and conversation-state correctness instead of CPU cycles.

Scope is held deliberately tight. This course does not train a speech-to-text or language model
from scratch, does not implement full adaptive acoustic echo cancellation, and does not build a
microphone array. Those remain, as the prerequisite course put it, entire further projects. What
this course finishes is the specific, honest gap between "detector" and "assistant that mostly
behaves."

## Prerequisites

**You need a working wake-word detector before Lab 1.** That is the binding design constraint of
this course, the same way "no prior FFT knowledge" was binding for its prerequisite.

- Completion of *Real-Time DSP on a $5 Microcontroller* (through at least [Chapter 28, Wake Word
  Detection](https://dmccreary.github.io/fft-benchmarking/chapters/28-wake-word-detection/)),
  **or** equivalent hands-on
  experience: I2S microphone capture, a correlation- or model-based wake-word detector with
  measured false-accept/false-reject rates, and comfort running MicroPython across both cores of an
  RP2350 with `_thread`.
- **Basic Python**, for the backend service — taught from zero if needed, faster with any prior
  server-side experience in any language.
- **A cloud account** with access to a speech-to-text and a text-to-speech API (any provider).
  This is a genuinely new requirement: every prior lab in the prerequisite course ran fully
  offline, and this is the first point in either course where a working internet connection and an
  external account are load-bearing, not optional.
- **Willingness to run two programs at once** — MicroPython on the board and a small Python server
  on a laptop or free-tier cloud host — and to read HTTP status codes when something goes wrong
  between them.

What is explicitly taught from zero, with no assumed background:

| Topic | First introduced |
|---|---|
| The I²S standard in full — frame formats, clocking, master/slave roles | Lab 1 |
| I²S **output**: DACs, class-D amplifiers, and driving a speaker | Lab 1 |
| Wi-Fi on the RP2350 and its cost to a real-time audio budget | Labs 4–6 |
| HTTP/HTTPS requests from MicroPython | Labs 5–6 |
| Streaming audio to a cloud speech-to-text endpoint | Labs 7–9 |
| Intent parsing and skill routing | Labs 10–12 |
| Text-to-speech playback over I²S | Labs 13–16 |
| Self-trigger suppression during playback | Labs 17–18 |
| Multi-turn conversation state | Labs 19–20 |
| Backend authentication, logging, and rate limiting | Labs 21–23 |

!!! note "On I²S specifically"
    The prerequisite course used I²S, but only as much of it as reading a microphone required —
    three wires, a 24-in-32 sample format, and a working capture loop. It never covered the
    standard itself, and it never sent audio *out*. This course treats I²S properly and in both
    directions, starting in Lab 1, because the moment a device has both a microphone and a
    speaker the details stop being trivia: frame format, word length, channel slots, who
    generates the clocks, and what the RP2350 can and cannot do with two audio devices at once.

## The Hardware Kit

Every student needs the prerequisite course's kit plus a small audio-output add-on and one extra
button, for roughly **$8 more** — or about **$10 more** if the board also has to be swapped from a
plain Pico 2 to a Pico 2 W.

| Component | Approx. cost | First used | Purpose |
|---|---|---|---|
| Raspberry Pi Pico 2 **W** (RP2350 + wireless) | $7 | Lab 1 | Now mandatory, not optional — every lab needs the radio |
| SSD1306 OLED, 128×64, SPI *(reused from prerequisite kit)* | $5 | Lab 1 | Status and debug display |
| INMP441 I²S MEMS microphone *(reused)* | $3 | Lab 1 | Wake-word capture, unchanged from the prerequisite course |
| Three momentary push buttons | $2 | Lab 1 | Mode select, plus up/down for volume and threshold adjustment |
| MAX98357A I²S class-D amplifier breakout | $4 | Lab 1 | Turns synthesized speech bytes into an analog speaker signal |
| Small 8Ω 2–3W speaker | $3 | Lab 1 | Spoken responses |
| Breadboard and jumper wires *(reused)* | $5 | Lab 1 | Connections |

The prerequisite course's kit used **two** buttons; this course adds a **third** so the three
controls the labs actually need — a mode selector plus an up/down pair — each get a dedicated
button instead of overloading one. Up/down drives speaker volume from Module 4 onward and the
wake-word detection threshold before that.

The plain Pico 2 (no **W**) cannot complete this course — unlike the prerequisite course, where the
wireless radio was optional until its very last chapter, here it is required starting in Lab 1.

**Software:** Thonny and stock MicroPython on the device, exactly as in the prerequisite course.
The backend service is plain Python (FastAPI or Flask — either works; the labs are written against
a small HTTP contract, not a specific framework) and can run on a laptop during development or a
free-tier host for the capstone. No speech model is trained locally; every STT and TTS call is a
network request to a cloud provider the student configures with their own API key.

## The Laboratory Series

Twenty-five labs of roughly 45–60 minutes each, in nine modules.

### Module 0 — The Signal Path and a Trusted Baseline (Labs 1–3)

Before adding anything, establish what the hardware does and what the existing detector is worth.

**Lab 1 — Setup, wiring, and the I²S standard in both directions.** The kit gains an audio
*output* for the first time, which makes I²S worth understanding properly rather than copying.
Students wire a microphone and an amplifier, then work through the standard itself: the three
wires and what each carries, frame format and word length, left/right channel slots, which device
is master and which is slave, and how a 24-bit sample ends up inside a 32-bit word. The concrete
payoff is being able to answer a question the wiring immediately raises — *why can't the
microphone and the speaker share one I²S bus?* — from the standard and from the RP2350's PIO
implementation of it, rather than from folklore.

**Lab 2 — The real-time budget.** At 12,800 Hz, 256 samples *is* 20 ms of sound. Students measure
how much of that budget an FFT actually consumes, comparing implementations carried over from the
prerequisite course, and confirm there is headroom for a continuous pipeline before writing one.

**Lab 3 — The detector baseline.** Students stand up the wake-word detector from the prerequisite
course (or provided starter firmware) on their own board, re-measure its false-accept and
false-reject rates, and instrument wake-to-decision latency — the clock this entire course is
trying not to blow.

### Module 1 — Getting the Pico 2 W Online Without Losing the Microphone (Labs 4–6)

Wi-Fi join, a minimal HTTPS client, and — the load-bearing measurement — how much CPU time and RAM
joining a network and holding a TLS session actually costs, measured against the same real-time
audio budget Chapter 18 of the prerequisite course established. Students confirm Core 0's sample
deadline survives the radio coming on.

### Module 2 — Shipping Audio to the Cloud (Labs 7–9)

Extending Post-Wake Audio Capture into a network upload: chunked streaming versus batch upload,
calling a cloud speech-to-text endpoint, and handling the case the prerequisite course never had to
consider — the trigger fires and the network is down.

### Module 3 — From Transcript to Intent (Labs 10–12)

Turning free text into a structured command: a small intent-and-slot parser, a skill router with a
handful of registered skills, and an honest fallback path for an utterance nothing recognizes.

### Module 4 — Talking Back (Labs 13–16)

A cloud text-to-speech request, streaming synthesized audio back to the board, wiring and driving
the I²S amplifier and speaker, and measuring the full wake-to-spoken-response latency budget
end to end for the first time.

### Module 5 — Not Hearing Yourself Talk (Labs 17–18)

The self-trigger problem: a speaker playing a response a few centimeters from a microphone that is
still listening. Students implement the practical mitigation this course actually ships —
mute-and-resume around playback — and are shown, honestly, why *true* acoustic echo cancellation
(an adaptive filter against a reference signal) is a further DSP project this course does not
build.

### Module 6 — Remembering the Conversation (Labs 19–20)

Session state on the backend, a timeout window for follow-up questions without repeating the wake
word, and the rule for when the assistant should require the wake word again rather than guessing.

### Module 7 — A Real(er) Backend (Labs 21–23)

API keys and request authentication, structured logging, rate limiting, and deploying the backend
to a real host with secrets kept out of both the device firmware and source control.

### Module 8 — Capstone: One Real Skill (Labs 24–25)

An end-to-end skill of the student's choosing — a timer, a trivia lookup, a smart-home-style
toggle — built on the full pipeline and reported with the same standard the prerequisite course's
capstone used: honestly measured latency and accuracy, limitations stated, no revised predictions
after the fact.

## What Students Measure Themselves

Every number below comes from the student's own device and backend, not a datasheet or a vendor's
marketing page.

| Stage | What gets measured |
|---|---|
| Real-time budget (Lab 2) | FFT cost as a percentage of one audio frame, and the headroom left over |
| Wake-word baseline (Lab 3) | False-accept and false-reject rate, re-confirmed on this course's hardware |
| Wi-Fi join and TLS (Lab 6) | CPU and RAM cost of the radio, measured against the audio-frame deadline |
| Cloud STT round trip (Lab 9) | Upload time, transcription latency, and failure behavior with Wi-Fi forced off |
| End-to-end response (Lab 16) | Full wake-to-spoken-response latency, wake word through spoken reply |
| Self-trigger suppression (Lab 18) | False-accept rate *during the assistant's own playback*, before and after mitigation |
| Capstone skill (Lab 25) | Latency and accuracy for one complete, student-chosen task |

## Content Covered

**The I²S standard, in both directions**
The bus properly rather than by recipe, because this is the first kit in either course with both
an audio input and an audio output. Bit clock, word select, and serial data, and why the data line
is strictly directional; frame format and word length; left/right channel slots and how a mono
device picks one; master versus slave roles, and the fact that ordinary MEMS microphones and
class-D amplifiers are *both* slaves so the microcontroller must clock both; sample formats
including the 24-bit-in-a-32-bit-word packing; the difference between I²S proper and the
left-justified and right-justified variants a datasheet may offer; and MCLK, where it is required
and where it is not.

On the output side: how a DAC or class-D amplifier turns a sample stream back into a speaker
signal, why a class-D amplifier wants a 5V supply rather than the 3V3 rail, buffered playback and
underrun, and what an amplifier does when it is clocked but has nothing to say.

On the RP2350 specifically: how MicroPython implements I²S on PIO rather than on dedicated audio
hardware, the two-instance limit, the half-duplex-per-instance rule, and the `ws = sck + 1`
adjacency constraint that follows from PIO sideset pins — together with the practical consequence
that a microphone and a speaker each need their own bus, and the three independent reasons that is
the right design here anyway.

**Networking on a constrained device**
Wi-Fi association, DNS, TLS handshakes, HTTP/HTTPS requests and status codes, chunked versus
buffered upload, timeouts and retry, and the CPU/RAM cost of all of the above on a chip that is
still expected to keep a real-time audio deadline.

**Cloud speech services**
Streaming versus batch audio upload, cloud speech-to-text request/response formats, cloud
text-to-speech synthesis and streamed audio playback, API keys and quota, and vendor-neutral
design so a specific provider is a configuration choice, not a hardcoded dependency.

**Language understanding, kept small**
Intents and slots, a rule-based or lightweight intent parser, skill routing, fallback and
clarification for unrecognized utterances — explicitly *not* a from-scratch trained NLU model.

**Audio playback and self-trigger suppression**
I²S DAC and class-D amplifier operation, buffered playback, the acoustic self-trigger problem, and
the honest distinction between a practical mute-and-resume mitigation and true adaptive acoustic
echo cancellation.

**Conversation and session state**
Multi-turn follow-up handling, context timeout windows, session identifiers, and the design
decision for when state should be discarded and the wake word required again.

**Backend service design**
A minimal HTTP contract between device and server, authentication with API keys, structured
request logging, rate limiting, secrets management, and deployment to a real (if teaching-scale)
host.

**Measurement and honesty, carried forward**
Wake-to-response latency budgets, false-accept measurement under realistic playback conditions, and
the same warm-up/statistics/exclusions discipline the prerequisite course's benchmarking module
taught, now applied to a distributed system instead of a single chip.

## Concepts Not Covered

This course closes some of the gaps the prerequisite course named as out of scope in Chapter 28 —
and deliberately leaves others open, for the same reason: they are each an entire further project.

**Now in scope, that Chapter 28 named as future work:**

- Full cloud speech-to-text and returning an actual transcription
- Intent parsing and skill routing
- A spoken response, via cloud text-to-speech and a real speaker
- Practical (not adaptive) suppression of the device re-triggering on its own voice
- Short-term multi-turn conversation state
- A real backend server with authentication, logging, and rate limiting

**Still out of scope, even in this course:**

- Training a custom speech-to-text or language-understanding model — every STT/TTS/NLU call in
  this course goes to an existing cloud provider
- True adaptive acoustic echo cancellation with a reference-signal filter — this course implements
  and clearly labels a simpler mute-and-resume mitigation instead
- Microphone arrays and far-field beamforming — the kit remains single-microphone throughout
- Multi-room or multi-device synchronization
- Production-grade compliance, encryption-at-rest, and account systems beyond a teaching-scale API
  key and rate limiter
- Retraining or replacing the on-device wake-word model itself — that was the prerequisite course's
  job, and this course treats it as a fixed, trusted baseline (Module 0)
- Audio interfaces other than I²S — PDM microphones, TDM multi-channel buses, analog codecs over
  I²C control channels, and USB audio are all named and compared in Lab 1 but never wired
- Writing custom PIO programs to get full-duplex I²S on one clock pair — the possibility is shown,
  and deliberately not taken, because this course stays on stock MicroPython

## Learning Outcomes

After this course, students will be able to demonstrate the following competencies, organized by
the 2001 revision of Bloom's Taxonomy. Outcomes marked **(lab)** are demonstrated by producing
working hardware, a working backend, or measurements, not by written answer alone.

### Remember

- List the network calls a wake-word firing sets in motion, in order, from trigger to spoken reply
- Name the three I²S signals, state which of them is directional, and identify which device drives
  each one **(lab)**
- Identify the I²S signals used for audio *output* and how they differ from the input wiring in the
  prerequisite course **(lab)**
- State the RP2350's I²S limits: two instances, half-duplex each, and `ws = sck + 1`
- Define intent, slot, skill, session state, rate limiting, and self-trigger suppression
- State the difference between batch and streaming audio upload
- Recall why full acoustic echo cancellation needs a reference signal that a mute-and-resume
  mitigation does not

### Understand

- Explain why an I²S data line cannot be shared between a microphone and an amplifier, and why the
  clock lines could be in principle but cannot be on this hardware **(lab)**
- Describe the master/slave roles on an I²S bus and explain why the microcontroller must be master
  for both the microphone and the amplifier
- Explain why joining Wi-Fi and holding a TLS session competes with the same real-time budget as
  audio capture **(lab)**
- Describe how a raw transcript becomes a structured intent, and why a fallback path is necessary
- Explain why the device must ignore its own speaker output without literally going deaf to new
  wake words **(lab)**
- Summarize what a rate limiter and an API key each protect against, and why neither is optional on
  a public endpoint
- Explain why this course does not train its own speech or language model

### Apply

- Wire and configure two independent I²S buses — one receiving, one transmitting — on a single
  board, respecting the pin-adjacency constraint **(lab)**
- Join Wi-Fi from MicroPython and issue an authenticated HTTPS request to a cloud endpoint **(lab)**
- Stream buffered post-wake audio to a cloud speech-to-text endpoint and handle a dropped
  connection **(lab)**
- Implement an intent parser and skill router for at least two distinct commands **(lab)**
- Play cloud-synthesized speech through an I²S amplifier and speaker **(lab)**
- Implement mute-and-resume self-trigger suppression and re-measure the false-accept rate during
  playback **(lab)**
- Carry conversation state across a follow-up question within a defined timeout window **(lab)**
- Deploy a backend service with authentication, logging, and rate limiting to a real host **(lab)**

### Analyze

- Profile an end-to-end voice interaction by stage and identify where the latency budget is spent
  **(lab)**
- Diagnose a failure by bisecting the pipeline — device, network, backend, or cloud provider
  **(lab)**
- Compare the false-accept rate during playback before and after self-trigger suppression, and
  explain the residual gap **(lab)**
- Determine whether a conversation-state bug is a timeout problem, a session-identifier problem, or
  a client problem
- Distinguish an I²S wiring or clocking fault from a software fault, using the symptoms each
  produces **(lab)**

### Evaluate

- Judge whether a given latency measurement is fast enough for a specific skill, and justify the
  threshold
- Critique a backend design for a missing rate limit, an exposed API key, or an unauthenticated
  endpoint **(lab)**
- Assess whether a proposed feature belongs in this course's scope or is genuinely "a further
  project," using the same standard Chapter 28 of the prerequisite course applied
- Decide when a device should require the wake word again versus continuing a conversation
- Judge when spending two extra GPIO pins is preferable to writing custom PIO code, and articulate
  what that tradeoff buys

### Create

- Design and build one complete, end-to-end voice-assistant skill, from wake word to spoken
  response **(lab)**
- Construct a backend service that a device can talk to safely over an untrusted network **(lab)**
- Produce a capstone report with measured latency, measured accuracy, stated limitations, and no
  revised predictions after seeing the data **(lab)**

## Weekly Schedule

| Week | Module | Labs | Milestone |
|---|---|---|---|
| 1 | The Signal Path and a Trusted Baseline | 1–3 | Kit wired, I²S understood, detector re-verified |
| 2 | Getting Online | 4–6 | Board on Wi-Fi without missing an audio deadline |
| 3 | Shipping Audio to the Cloud | 7–9 | **First real cloud transcript from a live trigger** |
| 4 | From Transcript to Intent | 10–12 | Working intent parser and skill router |
| 5 | Talking Back | 13–16 | **First full wake-to-spoken-response round trip** |
| 6 | Not Hearing Yourself Talk | 17–18 | Self-trigger rate measured and suppressed |
| 6–7 | Remembering the Conversation | 19–20 | Multi-turn follow-up handled correctly |
| 7 | A Real(er) Backend | 21–23 | Backend deployed with auth, logging, and rate limiting |
| 8 | Capstone | 24–25 | One complete skill, end to end, honestly measured |

The capstone is scoped for one to two weeks and may extend past Week 8 in an independent study
arrangement.

## Grading

| Component | Weight | Notes |
|---|---|---|
| Laboratory work | 30% | 25 labs; instructor decides completion vs. artifact grading |
| Homework and quizzes | 15% | Chapter quizzes and check-your-understanding items |
| Midterm | 15% | End of Week 5, covering Modules 0–4 |
| Backend security review | 15% | Peer or instructor review against the Module 7 checklist |
| Capstone project | 20% | Report weighted toward honest measurement, not raw latency |
| Final exam | 5% | Cumulative, emphasizing analysis and evaluation |

**On grading the capstone:** exactly as in the prerequisite course, a negative or partial result,
honestly reported and explained, receives full marks. An unexplained clean success does not. The
single unacceptable error remains revising a prediction after seeing the data.

## Instructor Notes

Three design decisions worth knowing about in advance:

1. **This course is deliberately cloud-provider-agnostic.** Labs are written against a plain HTTP
   contract for speech-to-text and text-to-speech, not a specific vendor SDK, so an instructor can
   substitute providers for cost or availability reasons without rewriting labs. Budget for a small
   per-student cloud API cost across the term.
2. **The self-trigger mitigation in Module 5 is intentionally the simple one.** True adaptive
   acoustic echo cancellation is a substantial DSP topic on its own; teaching it properly would
   roughly double this course. Module 5 is explicit with students about exactly what mute-and-resume
   does and does not solve, and a from-scratch AEC implementation is offered as an optional,
   advanced capstone track rather than a required lab.
3. **Module 0 is a trust boundary, not busywork.** Students arrive with wake-word detectors of
   varying quality from the prerequisite course. Re-measuring false-accept/false-reject before
   building anything new gives a real baseline to compare against in Module 5, and surfaces a weak
   detector before six modules of work are built on top of it.
