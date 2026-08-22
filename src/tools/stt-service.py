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
