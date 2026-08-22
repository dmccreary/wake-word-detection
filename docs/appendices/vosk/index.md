---
title: "Appendix B: Vosk — Offline Speech-to-Text on Your Own Machine"
description: Installing Vosk 0.3.44 on macOS or Windows WSL, turning a WAV file into a text string, and running it as a local service the Pico can call over the network
---

# Appendix B: Vosk — Offline Speech-to-Text on Your Own Machine

## The Short Answer

Three commands and about a minute of downloading gets you a speech recognizer that runs entirely
on your own machine, needs no account, no API key, and no internet connection after the model is
downloaded:

```bash
pip install vosk==0.3.44
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip -d models/
```

Point it at a WAV file of someone saying *"Hey Pico, set a timer for five minutes"* and you get
back exactly this string:

```
hey pico set a timer for five minutes
```

Lowercase, no punctuation, number **words** rather than digits. Those three properties are not
cosmetic — everything you build on top of the transcript has to expect them, and
[Working With the Transcript](#working-with-the-transcript) explains why.

!!! info "Where this fits in the course"
    Labs 8–10 send audio to a **cloud** speech-to-text endpoint, because that is what a commercial
    smart speaker does and because the latency and failure modes of a network round trip are part
    of what this course is about. Vosk is the offline stand-in for that endpoint: same shape —
    the board captures, something bigger recognizes — but the audio never leaves your desk, there
    is no bill, and it keeps working on a classroom Wi-Fi network that blocks half the internet.
    It is the right thing to develop against and a perfectly reasonable thing to ship.

## What Vosk Actually Is

Vosk is a thin, friendly Python wrapper around **Kaldi**, the speech-recognition toolkit that most
academic and industrial ASR work was built on for a decade. Kaldi itself is famously difficult to
approach — a research toolkit of shell scripts and compiled binaries. Vosk hides all of it behind
four objects:

| Object | What it is |
|---|---|
| `Model` | The acoustic + language model loaded from a directory on disk. Expensive to create, cheap to share. Thread-safe |
| `KaldiRecognizer` | One decoding session at one sample rate. Cheap to create, **not** thread-safe |
| `AcceptWaveform(pcm)` | Feed it raw 16-bit PCM bytes. Returns `True` when it has decided an utterance ended |
| `Result()` / `PartialResult()` / `FinalResult()` | JSON strings out |

That is the whole API surface you need. The `libvosk` shared library that does the real work ships
inside the wheel — there is nothing to compile, and no Kaldi installation anywhere on your system.

### Two version numbers that look like one

This trips up nearly everyone, so it is worth being explicit:

- **Vosk 0.3.44** is the version of the *Python package* — the code.
- **vosk-model-small-en-us-0.15** carries its own version — the *model*, the data.

They move independently. Package 0.3.44 runs the 0.15 small model, the 0.22 large model, and the
0.42 Gigaspeech model equally well. When someone says "I'm using Vosk 0.15" they mean the model,
and when the release notes talk about 0.3.44 they mean the library.

### Why 0.3.44 specifically

Because on a Mac it is the only choice pip will make. The published wheels stop there:

| Version | macOS | Linux x86-64 | Linux aarch64 | Linux armv7 | Windows |
|---|---|---|---|---|---|
| **0.3.44** (Sep 2022) | ✅ universal2 | ✅ | ✅ | ✅ | ✅ 64- and 32-bit |
| 0.3.45 (Dec 2022) | ❌ **none** | ✅ | ✅ | ✅ | ✅ 64-bit only |

0.3.45 is the newest release on PyPI, and it shipped without a macOS wheel. So `pip install vosk`
on any Mac resolves to **0.3.44** — you can watch it happen:

```bash
pip index versions vosk
```

```
vosk (0.3.44)
Available versions: 0.3.44, 0.3.43, 0.3.42, 0.3.41, 0.3.40, 0.3.38
```

On Linux and WSL, the same command offers 0.3.45. **Pin `vosk==0.3.44` on both** so the Mac half
of the class and the WSL half are running identical code — otherwise a bug report from one is not
reproducible on the other, which is a miserable way to spend a lab session.

The macOS wheel is `universal2`, meaning the bundled `libvosk.dyld` contains both x86-64 and arm64
code and runs natively on Apple Silicon. No Rosetta, no `arch -x86_64` prefix.

## Installing

### macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install vosk==0.3.44
```

Nothing else. No Homebrew package, no Xcode command line tools, no PortAudio — that last one only
matters if you want to capture from the Mac's own microphone, which this course does not, because
the microphone is on the Pico.

### Windows, via WSL

Two honest options, and the recommendation is not automatic:

| | Native Windows | WSL (Ubuntu) |
|---|---|---|
| Vosk wheel | ✅ `win_amd64` | ✅ `manylinux2010_x86_64` |
| Shell scripts in this repo | ✗ need rewriting | ✅ run as written |
| Serial port to the Pico | ✅ `COM3` — just works | ⚠️ needs `usbipd-win` to pass the USB device through |
| Reaching the service from the Pico over Wi-Fi | ✅ nothing to configure | ⚠️ see [Reaching the Service](#reaching-the-service-from-the-pico) |

**Use WSL if you want the same commands as everyone else in the class; use native Windows if the
Pico is plugged into that machine and you would rather not fight USB passthrough.** Vosk itself is
equally happy either way.

In WSL:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip unzip
python3 -m venv .venv && source .venv/bin/activate
pip install vosk==0.3.44 numpy
```

!!! warning "Keep the project on the Linux filesystem"
    Work in `~/wake-word-detection`, not `/mnt/c/Users/...`. Reading a 68 MB model across the
    9P filesystem bridge on every service start is slow enough to notice, and file-permission
    behavior on `/mnt/c` surprises Python in ways that have nothing to do with speech recognition.

## Choosing a Model

The package is useless without a model directory. All of these are Apache 2.0 licensed and free to
redistribute, which is part of why Vosk is a reasonable choice for a course.

| Model | Download | Published WER (librispeech test-clean) | Use it when |
|---|---|---|---|
| **vosk-model-small-en-us-0.15** | 41 MB (68 MB unpacked) | 9.85% | **Start here.** Fixed command sets, Raspberry Pi, anything latency-sensitive |
| vosk-model-en-us-0.22-lgraph | 128 MB | 7.82% | You need better accuracy but still want a dynamic graph |
| vosk-model-en-us-0.22 | 1.8 GB | 5.69% | Open-ended dictation on a machine with RAM to spare |
| vosk-model-en-us-0.42-gigaspeech | 2.3 GB | 5.64% | Podcast-style audio; explicitly not tuned for telephony |

For this course the small model is not a compromise you tolerate — it is the right answer. The
command vocabulary is tiny, the latency budget is tight, and as
[Restricting the Vocabulary](#restricting-the-vocabulary) shows, constraining what the recognizer
is allowed to hear buys far more accuracy on a fixed command set than a 25× larger model does.

```bash
mkdir -p models
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip -d models/
rm vosk-model-small-en-us-0.15.zip
```

You should end up with `models/vosk-model-small-en-us-0.15/` containing `am/`, `conf/`, `graph/`,
`ivector/`, and a `README`. The two big files inside `graph/` are `HCLr.fst` (22 MB, the acoustic
graph) and `Gr.fst` (24 MB, the language model) — the second one is what
[the vocabulary trick](#restricting-the-vocabulary) replaces at runtime.

## Your First Transcription

You do not need a microphone to test this, and you should not need one — a test that depends on
someone speaking is a test you will stop running. Both platforms can synthesize a mono 16-bit PCM
WAV, which is the format Vosk requires:

=== "macOS"

    ```bash
    say -o test.wav --data-format=LEI16@16000 "Hey Pico, set a timer for five minutes"
    ```

=== "WSL"

    ```bash
    sudo apt install -y espeak-ng
    espeak-ng -w test.wav -s 140 "Hey Pico, set a timer for five minutes"
    ```

`say` writes at whatever rate you ask it for; `espeak-ng` always writes **22,050 Hz** and gives you
no way to change it. Both work here, because `transcribe.py` builds the recognizer at *the file's*
rate and lets Vosk resample from there to the model's rate internally. The thing Vosk will not
tolerate is audio arriving at a rate different from the one its recognizer was constructed with —
a distinction [The Audio Format Rules](#the-audio-format-rules) returns to, because it is the one
that bites this project.

Then `src/tools/transcribe.py`, which is the whole API in thirty lines:

```python title="src/tools/transcribe.py"
#!/usr/bin/env python3
"""Turn one WAV file into one line of text.  Usage: transcribe.py file.wav"""
import json, sys, wave
from vosk import Model, KaldiRecognizer, SetLogLevel

MODEL_DIR = "models/vosk-model-small-en-us-0.15"

SetLogLevel(-1)                       # Vosk logs a dozen Kaldi lines otherwise

wf = wave.open(sys.argv[1], "rb")
if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
    sys.exit("need mono 16-bit PCM WAV")

rec = KaldiRecognizer(Model(MODEL_DIR), wf.getframerate())
rec.SetWords(True)
rec.AcceptWaveform(wf.readframes(wf.getnframes()))
result = json.loads(rec.FinalResult())

print(result["text"])
for w in result.get("result", []):
    print("  %5.2f-%5.2f  %-10s conf %.2f" % (w["start"], w["end"], w["word"], w["conf"]))
```

```bash
python3 src/tools/transcribe.py test.wav
```

```
hey pico set a timer for five minutes
   0.06- 0.27  hey        conf 1.00
   0.27- 0.81  pico       conf 1.00
   0.90- 1.17  set        conf 1.00
   1.17- 1.20  a          conf 1.00
   1.20- 1.62  timer      conf 1.00
   1.62- 1.77  for        conf 1.00
   1.77- 2.13  five       conf 1.00
   2.13- 2.58  minutes    conf 1.00
```

`SetWords(True)` is what adds the per-word timings and confidences. It costs nothing and it is the
difference between debugging a bad transcript and guessing at one — when a command is
misunderstood, the word timings usually show you that the audio was clipped at one end rather than
that the recognizer was confused.

## The Audio Format Rules

Vosk is strict in one specific way and forgiving everywhere else.

**It requires 16-bit signed PCM, mono.** Feed it a 32-bit float WAV, an MP3, or a stereo file and
you get nonsense or an exception.

**It will not resample.** The recognizer is constructed with a sample rate, and audio at any other
rate is refused outright — not quietly converted:

```
ERROR (VoskAPI:MaybeCreateResampler():online-feature.cc:99) Sampling frequency mismatch,
expected 16000, got 12800
Perhaps you want to use the options --allow_{upsample,downsample}
```

That error is worth recognizing on sight, because it is the one this project hits. The Pico
captures at **12,800 Hz** — a rate chosen in Lab 3 for the FFT, not for a speech recognizer — so
something has to convert. That conversion belongs on the host, and `stt-service.py` below does it
with linear interpolation.

!!! question "Why not just capture at 16 kHz on the Pico?"
    Because reopening the I²S stream at a different rate starts it with an empty buffer, and the
    command follows the wake word with no pause at all — *"Hey Pico, set a timer"* is one breath.
    Restarting the microphone there clips the first word off every command. A command missing its
    verb is worth far less than one missing a little treble. Upsampling 12.8 kHz to 16 kHz adds no
    information above the original 6.4 kHz Nyquist limit, and it does not need to: nearly all of
    the phonetic information that distinguishes English words lives below that.

You may set the recognizer's rate to match the *file* rather than the model — `KaldiRecognizer(model, 8000)`
for telephone audio, for example, and Vosk will resample internally to the model's rate. What it
will not do is accept a stream at a rate other than the one the recognizer was built with.

## Restricting the Vocabulary

This is the single most valuable thing in this appendix, and it is not obvious from the
documentation.

`KaldiRecognizer` takes an optional third argument: a JSON list of phrases. Supplying it swaps the
model's general-purpose language model for a tiny one built on the spot from your list. The
recognizer can then only produce words from that list — which, for a device that understands eleven
kinds of sentence, is exactly what you want.

```python
GRAMMAR = json.dumps([
    "hey pico", "set a timer for",
    "one two three four five six seven eight nine ten",
    "fifteen twenty thirty forty five sixty ninety",
    "second seconds minute minutes hour hours",
    "half and a",
    "[unk]",
])
rec = KaldiRecognizer(model, 16000, GRAMMAR)
```

Here is what it does to the ten real "Hey Pico" takes recorded on the kit and committed in
[`docs/sounds/`](../../dashboards/wake-word-explorer/index.md) — the same audio, the same model,
the same 12.8 → 16 kHz upsample, changing nothing but the grammar argument:

| Take | Open vocabulary | Restricted grammar |
|---|---|---|
| hey-pico-01 … 05, 07, 08 | `hey paco` | `hey pico` |
| hey-pico-06, 10 | `hey by go` | `hey pico` |
| hey-pico-09 | `they by go` | `hey pico` |
| **Correct** | **0 / 10** | **10 / 10** |

Zero to ten out of ten, for free, with no larger model and no retraining. The general-purpose
language model has never heard "Pico" as a name and confidently proposes a common word instead;
told that "pico" is one of only about forty words that can possibly occur, it has no alternative to
prefer.

**The catch is real and you must design around it.** A restricted recognizer maps *everything* to
the nearest thing in its list. Ask it a question it was never given words for, and without
protection it will invent a command out of the words it does have. That is what `"[unk]"` is for —
including it gives the recognizer permission to say it does not know:

| Utterance | Open vocabulary | Restricted grammar |
|---|---|---|
| "Hey Pico, what is the weather in Minneapolis tomorrow" | `hey pico what is the weather in minneapolis tomorrow` | `hey pico [unk]` |

`hey pico [unk]` is a *good* result. It is the difference between a device that says "sorry, I
didn't get that" and one that silently sets a 4-minute timer because "weather" sounded a little
like "for". **Always include `[unk]` in a restricted grammar.** Then treat any transcript
containing it as a non-command.

!!! tip "Grammar mode needs a dynamic-graph model"
    This works with the small models and the `-lgraph` models, which ship a rewritable `Gr.fst`.
    The large static models (`vosk-model-en-us-0.22`, `-gigaspeech`) have their language model
    compiled into the graph and do not support runtime vocabulary restriction at all. One more
    reason the small model is the right starting point here.

## Streaming Versus One-Shot

Everything so far handed Vosk a complete file. It is equally happy being fed a live stream, and the
difference matters for perceived latency: with streaming you get a partial transcript while the
person is still talking.

```python title="src/tools/stream.py — the loop that matters"
chunk = rate // 4 * 2                  # 0.25 s of 16-bit mono, in bytes
while True:
    data = wf.readframes(chunk // 2)
    if not data:
        break
    if rec.AcceptWaveform(data):
        print("final  ", json.loads(rec.Result())["text"])
    else:
        print("partial", json.loads(rec.PartialResult())["partial"])
print("FINAL  ", json.loads(rec.FinalResult())["text"])
```

```
 0.51s  partial hey
 0.53s  partial hey pico
 0.69s  partial hey pico set
 0.74s  partial hey pico set a
 0.76s  partial hey pico set a timer
 0.81s  partial hey pico set a timer for
 0.84s  partial hey pico set a timer for five
 0.91s  partial hey pico set a timer for five minutes
 0.91s  FINAL   hey pico set a timer for five minutes
```

`AcceptWaveform` returning `True` means Vosk has decided an utterance ended — usually on silence.
That is an endpointing decision, not a punctuation decision, and it is the hook a live assistant
uses to stop recording.

**For this course, one-shot is the right default.** The board already knows when the command
started (the wake word fired) and when it ended (the buffer filled or the speaker went quiet), so
it has a complete clip before it ever contacts the host. Streaming becomes interesting in Labs
8–10, where the point is to overlap the network transfer with the talking so the round trip does
not begin only after the person stops.

## Running It as a Local Service

A script that loads the model, transcribes one file, and exits pays half a second and 170 MB every
time. A service pays it once at startup. That is the entire reason to build one — plus the fact
that it puts a network boundary in exactly the place the rest of the course puts one, so the code
that talks to Vosk today can talk to a cloud endpoint in Lab 8 with the URL as the only change.

```python title="src/tools/stt-service.py"
#!/usr/bin/env python3
"""A local speech-to-text service: POST a WAV, get back JSON.

    python3 src/tools/stt-service.py                 # 127.0.0.1:5005
    python3 src/tools/stt-service.py --host 0.0.0.0  # reachable from the Pico

    curl --data-binary @clip.wav http://127.0.0.1:5005/stt

The model is loaded once at startup and reused for every request. That is the
entire reason this is a service and not a script: loading costs about half a
second and 170 MB, and paying it per utterance would dominate the response
time of everything built on top of it.
"""
import argparse, io, json, threading, time, wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from vosk import Model, KaldiRecognizer, SetLogLevel

ASR_RATE = 16000                       # what every Vosk en-us model expects
MAX_BYTES = 8 * 1024 * 1024            # ~4 minutes of 16 kHz mono; refuse more

REC = None
LOCK = threading.Lock()                # one recognizer, one utterance at a time


def to_pcm16k(body):
    """WAV bytes -> 16 kHz mono 16-bit PCM bytes. Raises ValueError if unusable.

    numpy rather than the stdlib `audioop`, which is deprecated in Python 3.12
    and gone in 3.13 -- a service meant to outlive one Python release should
    not be built on it.
    """
    with wave.open(io.BytesIO(body), "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
            raise ValueError("need 16-bit PCM WAV")
        rate, channels = wf.getframerate(), wf.getnchannels()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != ASR_RATE:
        # Vosk does not resample. It raises "Sampling frequency mismatch" and
        # refuses the audio, so the conversion has to happen on this side.
        n = int(len(pcm) * ASR_RATE / rate)
        t = np.arange(n) * (rate / ASR_RATE)
        i = np.clip(np.floor(t).astype(int), 0, len(pcm) - 2)
        f = t - i
        pcm = ((1 - f) * pcm[i] + f * pcm[i + 1]).astype(np.int16)
    return pcm.tobytes()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "rate": ASR_RATE})
        else:
            self._json(404, {"error": "POST audio to /stt"})

    def do_POST(self):
        if self.path != "/stt":
            return self._json(404, {"error": "POST audio to /stt"})
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0 or n > MAX_BYTES:
            return self._json(413, {"error": "body must be 1..%d bytes" % MAX_BYTES})
        body = self.rfile.read(n)
        try:
            pcm = to_pcm16k(body)
        except Exception as e:
            return self._json(400, {"error": str(e)})

        t0 = time.time()
        with LOCK:
            REC.AcceptWaveform(pcm)
            result = json.loads(REC.FinalResult())
            REC.Reset()                # or the next caller inherits this one
        seconds = len(pcm) / 2 / ASR_RATE
        self._json(200, {
            "text": result.get("text", ""),
            "words": result.get("result", []),
            "audio_seconds": round(seconds, 2),
            "decode_seconds": round(time.time() - t0, 2),
        })

    def log_message(self, fmt, *a):     # one tidy line instead of two noisy ones
        print("%s %s" % (self.address_string(), fmt % a), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/vosk-model-small-en-us-0.15")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5005)
    args = ap.parse_args()

    SetLogLevel(-1)
    global REC
    t0 = time.time()
    REC = KaldiRecognizer(Model(args.model), ASR_RATE)
    REC.SetWords(True)
    print("model loaded in %.2f s: %s" % (time.time() - t0, args.model), flush=True)

    # Warm up. The first decode after startup costs about 0.8 s against 0.09 s
    # for every one after it; this pass buys back part of that -- not all of
    # it, since most of the cold start belongs to the first decode of real
    # speech rather than to anything silence can trigger.
    REC.AcceptWaveform(b"\x00\x00" * ASR_RATE)
    REC.FinalResult()
    REC.Reset()

    print("listening on http://%s:%d/stt" % (args.host, args.port), flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
```

Standard library plus numpy — no Flask, no FastAPI, nothing to install beyond what Vosk already
needed. Start it and use it:

```bash
python3 src/tools/stt-service.py
```

```bash
curl -s --data-binary @test.wav http://127.0.0.1:5005/stt
```

```json
{"text": "hey pico set a timer for five minutes",
 "words": [...],
 "audio_seconds": 2.61,
 "decode_seconds": 0.72}
```

Send the same file again and `decode_seconds` drops to **0.08** — that gap is the cold start
discussed below, not a fluke.

A 12.8 kHz file straight off the Pico works through the same endpoint, because the service
resamples before Vosk ever sees it:

```bash
curl -s --data-binary @docs/sounds/hey-pico-01.wav http://127.0.0.1:5005/stt
```

```json
{"text": "hey paco", "audio_seconds": 3.0, "decode_seconds": 0.13}
```

### Three design decisions worth understanding

**One recognizer behind a lock.** `Model` is thread-safe and shareable; `KaldiRecognizer` is not.
`ThreadingHTTPServer` will happily run two requests at once, so the recognizer is serialized with a
`threading.Lock`. The alternative — a recognizer per thread — costs memory per thread and buys
throughput this service does not need, since one board makes one request at a time.

**`Reset()` after every request.** A recognizer carries state between utterances. Skip the reset
and request *n+1* inherits request *n*'s decoding context, which surfaces as a transcript with a
stranger's words at the front of it. This is the single most common bug in home-grown Vosk
services.

**The warm-up.** Measured on an M2 with the small model, the first decode after startup takes
**0.83 s** for a 2.6 s clip against **0.09 s** for every decode after it — Kaldi does a pile of lazy
initialization on first use. The warm-up pass recovers part of that, and only part: it brings the
first real decode to **0.74 s**, not to 0.09 s. Most of the cold-start cost belongs to the first
decode of actual *speech* and cannot be paid in advance with silence. It is still worth keeping —
it is free and it is measurably better — but do not expect the first request to be as fast as the
second, and do not go hunting for a bug when it isn't.

### Measured performance

Apple M2 (Mac14,2), Python 3.11.5, vosk 0.3.44, vosk-model-small-en-us-0.15:

| Measurement | Value |
|---|---|
| Model load | 0.44–0.53 s |
| Warm-up pass on 1 s of silence | 0.18–0.38 s |
| Resident memory after load | ≈172 MB |
| First decode of a 2.6 s clip, cold | 0.83 s — real-time factor 0.32 |
| First decode after the silence warm-up | 0.74 s — real-time factor 0.28 |
| Steady-state decode, same clip | 0.08–0.10 s — real-time factor **0.03–0.04** |
| Model on disk | 41 MB zipped, 68 MB unpacked |

A real-time factor of 0.03 means a 3-second command is transcribed in about a tenth of a second —
small enough that on a local network, speech recognition is *not* where your latency budget goes.
That is worth knowing before you start optimizing the wrong thing in Lab 10.

**Measure your own.** Every response carries `decode_seconds` for exactly this reason, and a WSL
machine on an x86 laptop will land somewhere different from an M2. The number above is a data
point, not a specification.

## Keeping It Running

During labs, run it in a terminal where you can see the log. When you want it always available:

=== "macOS — launchd"

    Save as `~/Library/LaunchAgents/local.vosk.stt.plist`, with the paths edited to match your
    machine:

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0"><dict>
      <key>Label</key><string>local.vosk.stt</string>
      <key>ProgramArguments</key>
      <array>
        <string>/Users/YOU/wake-word-detection/.venv/bin/python3</string>
        <string>/Users/YOU/wake-word-detection/src/tools/stt-service.py</string>
      </array>
      <key>WorkingDirectory</key><string>/Users/YOU/wake-word-detection</string>
      <key>RunAtLoad</key><true/>
      <key>KeepAlive</key><true/>
      <key>StandardOutPath</key><string>/tmp/vosk-stt.log</string>
      <key>StandardErrorPath</key><string>/tmp/vosk-stt.err</string>
    </dict></plist>
    ```

    ```bash
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.vosk.stt.plist
    ```

    Restart it after an edit with `launchctl kickstart -k gui/$(id -u)/local.vosk.stt`, and remove
    it with `launchctl bootout gui/$(id -u)/local.vosk.stt`. `WorkingDirectory` is load-bearing —
    the default model path is relative.

=== "WSL — systemd"

    systemd is off by default in WSL. Turn it on in `/etc/wsl.conf`:

    ```ini
    [boot]
    systemd=true
    ```

    Then `wsl --shutdown` from PowerShell and reopen the distro. Save as
    `/etc/systemd/system/vosk-stt.service`:

    ```ini
    [Unit]
    Description=Vosk local speech-to-text service
    After=network.target

    [Service]
    User=YOU
    WorkingDirectory=/home/YOU/wake-word-detection
    ExecStart=/home/YOU/wake-word-detection/.venv/bin/python3 src/tools/stt-service.py --host 0.0.0.0
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target
    ```

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable --now vosk-stt
    journalctl -u vosk-stt -f
    ```

    A WSL distro only runs while something is using it. The service comes up when you open a WSL
    terminal, not when Windows boots.

## Reaching the Service from the Pico

The default bind is `127.0.0.1`, which is correct while you are developing on one machine and
wrong the moment the board needs to call it. Two things have to change.

**Bind to all interfaces.** `--host 0.0.0.0`. Nothing else will do; `localhost` is not reachable
from another device by any amount of firewall configuration.

**Let the connection in.**

=== "macOS"

    The first time the service binds to `0.0.0.0`, macOS shows a dialog asking whether to allow
    incoming connections. Say yes. If you dismissed it, re-enable in System Settings → Network →
    Firewall → Options. Find the Mac's LAN address with:

    ```bash
    ipconfig getifaddr en0
    ```

    That is the address the Pico connects to — `http://192.168.1.x:5005/stt`.

=== "WSL — mirrored networking (recommended)"

    On Windows 11 22H2 and later, WSL can mirror the host's network interfaces instead of sitting
    behind NAT, which makes the LAN able to reach WSL directly. In
    `%UserProfile%\.wslconfig`:

    ```ini
    [wsl2]
    networkingMode=mirrored
    ```

    `wsl --shutdown` to apply. Then allow inbound connections through the Hyper-V firewall, in an
    **administrator** PowerShell:

    ```powershell
    New-NetFirewallHyperVRule -Name "VoskSTT" -DisplayName "Vosk STT" -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts 5005
    ```

    The Pico then connects to the **Windows** machine's LAN address on port 5005.

=== "WSL — NAT mode (the default)"

    Under NAT, WSL 2 has its own virtual adapter and its own IP address, so the LAN cannot see it.
    Forward the port from Windows into the VM, in an **administrator** PowerShell:

    ```powershell
    netsh interface portproxy add v4tov4 listenport=5005 listenaddress=0.0.0.0 connectport=5005 connectaddress=(wsl hostname -I).Trim()
    New-NetFirewallRule -DisplayName "Vosk STT" -Direction Inbound -Protocol TCP -LocalPort 5005 -Action Allow
    ```

    !!! warning "The WSL IP changes"
        The VM gets a new address on most restarts, and the port proxy keeps pointing at the old
        one — which looks exactly like the service having crashed. Re-run the `portproxy` command
        after a `wsl --shutdown`, or switch to mirrored mode and stop thinking about it. Inspect
        the current rules with `netsh interface portproxy show all`.

!!! danger "This service has no authentication"
    Anything that can reach port 5005 can send it audio and consume its CPU. On a home network
    that is acceptable. On campus Wi-Fi, a shared lab network, or anywhere you do not control,
    keep the bind on `127.0.0.1` and reach it over the USB cable instead — which is exactly what
    [`src/tools/hey-pico-server.py`](https://github.com/dmccreary/wake-word-detection/blob/main/src/tools/hey-pico-server.py)
    does, shipping audio over the serial link and never opening a socket at all. Authentication,
    rate limiting, and logging are the subject of Labs 22–24, and this appendix deliberately does
    not front-run them.

## Working With the Transcript

Vosk hands back a normalized string, and "normalized" costs you things you may be assuming are
there:

| What you get | What that means for your code |
|---|---|
| `hey pico set a timer for five minutes` | No capitalization to key on — `"Pico"` never appears |
| No punctuation at all | You cannot detect a question by looking for `?` |
| Number **words**: `five`, not `5` | `int(token)` fails on every spoken number |
| `twenty five`, not `twenty-five` | Compound numbers arrive as two tokens |
| Confidence per word, only with `SetWords(True)` | Off by default |

The number-words point is the one that bites hardest, and it is why
`src/tools/hey-pico-server.py` carries a `words_to_number()` function of its own — a
device that understood "set a timer for 5 minutes" but not "set a timer for five minutes" would
fail on every sentence a human actually says. That parser also handles the things people say out
loud that written examples never show: *"two and a half minutes"*, *"half an hour"*, *"an hour and
a half"*.

Large cloud speech APIs often do this normalization for you, returning `5` and `Pico` and a
question mark. When Lab 8 swaps this service for a cloud endpoint, expect the intent parser to
need adjusting in *both* directions — that difference is a real part of what changes when you cross
that boundary, not an accident of this appendix.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Sampling frequency mismatch, expected 16000, got 12800` | Vosk never resamples. Convert on your side, or build the recognizer at the file's rate |
| Empty transcript, no error | Almost always format. Confirm mono, 16-bit, PCM: `python3 -c "import wave,sys; w=wave.open(sys.argv[1]); print(w.getnchannels(), w.getsampwidth(), w.getframerate())" file.wav` |
| A dozen `LOG (VoskAPI:...)` lines on stderr | Normal. `SetLogLevel(-1)` before creating the `Model` silences them |
| `Missing FFMPEG, please install and try again` | The bundled `vosk-transcriber` CLI shells out to ffmpeg even for a plain 16 kHz WAV. `brew install ffmpeg` / `sudo apt install ffmpeg`, or use the Python API, which does not need it |
| Transcript contains words from the *previous* request | Missing `Reset()` between utterances |
| Words that were never spoken, in a restricted grammar | Working as designed — the grammar has no other options. Add `[unk]` and reject transcripts containing it |
| `ERROR: Could not find a version that satisfies the requirement vosk` on a Mac | You asked for 0.3.45 or newer. There is no macOS wheel past 0.3.44 |
| Pico gets a connection refused | The service is bound to `127.0.0.1`. Restart with `--host 0.0.0.0` |
| Worked yesterday, refuses connections today (WSL, NAT mode) | The WSL VM's IP changed and the `portproxy` rule points at the old one |
| First command after startup is slower, the rest are fast | Expected. Kaldi initializes lazily on first use; the warm-up in `main()` reduces it but does not remove it |

## What This Is Not

Vosk is a good recognizer, not a state-of-the-art one. The small model's published 9.85% word error
rate on clean read speech is well behind a current large cloud model, and the gap widens in a noisy
room with an unfamiliar accent. What it gives you instead is a recognizer that runs on your desk, costs nothing per request, never sends
audio anywhere, and is fast enough that recognition latency is not the problem you are solving.

It also does not understand anything. A transcript is a string; deciding that
`set a timer for five minutes` means `{"intent": "timer", "seconds": 300}` is a separate job, and
it is the subject of Labs 11–13. Confusing the two is the most common way a first voice-assistant
project goes wrong: the recognizer gets blamed for what is really a missing intent layer.

---

## Sources

- [vosk 0.3.44 on PyPI](https://pypi.org/project/vosk/0.3.44/#files) — wheel platform tags, release date (September 2022), Apache 2.0
- [vosk 0.3.45 on PyPI](https://pypi.org/project/vosk/0.3.45/#files) — the release with no macOS wheel
- [Vosk models](https://alphacephei.com/vosk/models) — model list, sizes, published word error rates
- [Vosk API on GitHub](https://github.com/alphacep/vosk-api) — source, issues, other language bindings
- [Accessing network applications with WSL](https://learn.microsoft.com/en-us/windows/wsl/networking) — Microsoft: NAT versus mirrored networking, `netsh portproxy`, Hyper-V firewall rules
- Timings, memory figures, and every transcript on this page were measured on an Apple M2 (Mac14,2) with Python 3.11.5, vosk 0.3.44, and vosk-model-small-en-us-0.15, using the ten recorded takes committed in `docs/sounds/`.
