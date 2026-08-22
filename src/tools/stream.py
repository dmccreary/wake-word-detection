#!/usr/bin/env python3
"""Feed a WAV in 0.25 s chunks and watch the transcript grow."""
import json, sys, time, wave
from vosk import Model, KaldiRecognizer, SetLogLevel

SetLogLevel(-1)
wf = wave.open(sys.argv[1], "rb")
rate = wf.getframerate()
rec = KaldiRecognizer(Model("models/vosk-model-small-en-us-0.15"), rate)

chunk = rate // 4 * 2                  # 0.25 s of 16-bit mono, in bytes
t0 = time.time()
while True:
    data = wf.readframes(chunk // 2)
    if not data:
        break
    if rec.AcceptWaveform(data):
        print("%5.2fs  final   %s" % (time.time() - t0, json.loads(rec.Result())["text"]))
    else:
        p = json.loads(rec.PartialResult())["partial"]
        if p:
            print("%5.2fs  partial %s" % (time.time() - t0, p))
print("%5.2fs  FINAL   %s" % (time.time() - t0, json.loads(rec.FinalResult())["text"]))
