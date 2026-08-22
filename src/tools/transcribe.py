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
