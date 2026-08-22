#!/usr/bin/env python3
"""The host half of Hey Pico: speech recognition on the other end of the cable.

    python3 src/tools/hey-pico-server.py

This owns the serial port, starts `src/labs/hey-pico-timer.py` on the Pico,
and then waits. When the board hears its wake word it records the command that
follows and sends the audio here; this recognizes the words, works out how long
a timer was asked for, and answers with one line.

It stands in for the cloud service a commercial smart speaker would call, and
it is deliberately the same shape: the device does the cheap always-on part,
the server does the expensive on-demand part, and the wake word is the thing
that decides when to spend. The difference is that here you can read the whole
server, and the audio never leaves the desk.

SETUP -- Vosk, offline, no API key:

    pip install vosk
    curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip vosk-model-small-en-us-0.15.zip -d models/

WHAT IT UNDERSTANDS

    "set a timer for five minutes"      -> 300 s
    "timer for ninety seconds"          ->  90 s
    "set a timer for two and a half minutes" -> 150 s
    "one hour timer"                    -> 3600 s

Anything else comes back as SORRY and the board says so.
"""

import argparse
import base64
import glob
import json
import os
import re
import sys
import time
import wave

try:
    import serial
except ImportError:
    sys.exit("pyserial missing:  pip install pyserial")

try:
    import numpy as np
except ImportError:
    sys.exit("numpy missing:  pip install numpy")

# Three dirnames, not two: this file lives at <repo>/src/tools/, so peeling
# off tools/ and src/ is what reaches the repo root the other paths hang from.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PICO_PROGRAM = os.path.join(ROOT, "src", "labs", "hey-pico-timer.py")
MODEL_GLOB = os.path.join(ROOT, "models", "vosk-model*")

HDR = "<<<AUDIO"
FTR = "<<<END>>>"
MAX_TIMER_S = 24 * 3600

# Vosk will not accept anything but its model's rate -- it does not resample
# quietly, it raises "Sampling frequency mismatch, expected 16000, got 12800"
# and refuses the audio outright. So the conversion happens here.
#
# The alternative was to reopen the microphone at 16 kHz just for the command,
# which would capture real detail up to 8 kHz instead of interpolating toward
# it. That was rejected on purpose: reopening an I2S stream starts it with an
# empty buffer, and the command follows the wake word with no pause at all --
# "Hey Pico, set a timer" is one breath. Restarting the mic there would clip
# the first word off every command, and a command missing its verb is worth far
# less than one missing a little treble.
ASR_RATE = 16000

# --- turning words into numbers --------------------------------------------
# Vosk emits number WORDS, not digits: "five", not "5". A wake-word demo that
# only understood digits would fail on every sentence a person actually says.
UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "a": 1, "an": 1, "1": 1,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
UNIT_SECONDS = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60,
                "hour": 3600, "hours": 3600}


def words_to_number(tokens):
    """Turn a run of number words into a value. Returns None if there is none.

    Handles "ninety" and "ninety five" and a bare "90", plus the "and a half"
    that people say out loud far more often than written examples suggest.
    """
    total = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.isdigit():
            total = (total or 0) + int(t)
        elif t in TENS:
            v = TENS[t]
            if i + 1 < len(tokens) and tokens[i + 1] in UNITS and UNITS[tokens[i + 1]] < 10:
                v += UNITS[tokens[i + 1]]
                i += 1
            total = (total or 0) + v
        elif t in UNITS:
            # "a" means one in "a minute" but nothing at all in "and a half",
            # where the value is carried entirely by the word after it. Adding
            # 1 there turns two and a half minutes into three and a half.
            if t in ("a", "an") and i + 1 < len(tokens) and tokens[i + 1] == "half":
                pass
            else:
                total = (total or 0) + UNITS[t]
        elif t == "half":
            total = (total or 0) + 0.5
            # "half a minute" -- the article belongs to the half, not to a
            # separate one. Without this it reads as one and a half.
            if i + 1 < len(tokens) and tokens[i + 1] in ("a", "an"):
                i += 1
        elif t == "and":
            pass                       # "two and a half" -- keep accumulating
        else:
            break
        i += 1
    return total


def parse_timer(text):
    """Pull a duration out of recognized speech. Returns (seconds, spoken) or None.

    Scans for a UNIT word and reads the number words immediately before it, so
    "set a timer for five minutes" and "five minute timer" both work without
    needing a grammar for every phrasing.
    """
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    total = 0.0
    found = False
    for i, t in enumerate(tokens):
        if t not in UNIT_SECONDS:
            continue
        start = i
        while start > 0 and (tokens[start - 1] in UNITS or tokens[start - 1] in TENS
                             or tokens[start - 1] in ("and", "half")
                             or tokens[start - 1].isdigit()):
            start -= 1
        n = words_to_number(tokens[start:i])
        if n is None:
            continue
        # A half can also trail the unit -- "an hour and a half" carries the
        # same meaning as "one and a half hours" and people say both.
        tail = tokens[i + 1:i + 4]
        if tail[:3] == ["and", "a", "half"] or tail[:2] == ["and", "half"]:
            n += 0.5
        total += n * UNIT_SECONDS[t]
        found = True
    if not found or total <= 0:
        return None
    seconds = int(round(total))
    if seconds > MAX_TIMER_S:
        return None
    return seconds, describe(seconds)


def describe(seconds):
    """The sentence the board displays and prints back to you."""
    if seconds % 3600 == 0 and seconds >= 3600:
        n, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds, "second"
    # Singular unit on purpose: "5 minute timer running", not "5 minutes".
    # It is a compound adjective here, the way a person would say it out loud.
    return "%d %s timer running" % (n, unit)


# --- speech recognition -----------------------------------------------------

def resample(x, src, dst):
    """Linear interpolation between rates. Good enough, and measurably so.

    Upsampling 12800 -> 16000 is a ratio of 5:4, and no interpolation can add
    information above the original 6.4 kHz Nyquist. What matters is whether
    the result is recognizable, and on the ten sample takes in docs/sounds/ it
    is: "hey" comes back from 9 of 10. ("Pico" itself returns as "paco" -- the
    name is not in the model's vocabulary, which costs nothing here because the
    wake word is matched on the chip and Vosk only ever sees the command.)
    """
    if src == dst:
        return x
    n = int(len(x) * dst / src)
    t = np.arange(n) * (src / dst)
    i = np.clip(np.floor(t).astype(int), 0, len(x) - 2)
    f = t - i
    return ((1 - f) * x[i] + f * x[i + 1]).astype(np.int16)


def load_recognizer(model_dir, rate):
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)                    # vosk is chatty on stderr by default
    rec = KaldiRecognizer(Model(model_dir), rate)
    rec.SetWords(False)
    return rec


def recognize(rec, pcm_bytes):
    rec.AcceptWaveform(pcm_bytes)
    text = json.loads(rec.FinalResult()).get("text", "")
    rec.Reset()
    return text


# --- the serial side --------------------------------------------------------

def start_program(ser, source):
    """Drop into the raw REPL and run the Pico program from there.

    Raw REPL rather than the friendly one because the friendly REPL echoes
    everything typed at it and interleaves '>>> ' prompts, which would land in
    the middle of the base64 audio stream.
    """
    ser.write(b"\r\x03\x03")           # Ctrl-C twice: stop whatever is running
    time.sleep(0.3)
    ser.write(b"\r\x02")               # Ctrl-B: make sure we are at the friendly REPL

    # SOFT RESET, and it is not optional.
    #
    # The raw REPL does not restart the interpreter, so every program run
    # before this one has left its module-level objects sitting in the REPL's
    # globals where gc.collect() cannot touch them. On a board that had been
    # exercised for an afternoon that cost 200 KB: 295 KB free instead of 482,
    # and the board's 76,800-byte audio buffer failed to allocate. The symptom
    # is a MemoryError whose size looks like it should obviously fit.
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.write(b"\x04")                  # Ctrl-D: soft reboot
    time.sleep(1.2)
    ser.write(b"\r\x03")               # stop boot.py/main.py if the kit has one
    time.sleep(0.3)

    ser.reset_input_buffer()
    ser.write(b"\r\x01")               # Ctrl-A: raw REPL
    time.sleep(0.3)
    banner = ser.read(400)
    if b"raw REPL" not in banner:
        raise SystemExit("could not enter raw REPL; is another program holding "
                         "the port? (Thonny, mpremote, a second copy of this)")
    ser.write(source.encode() + b"\x04")
    time.sleep(0.4)
    ser.read(4)                        # the 'OK' that acknowledges the paste


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default=None, help="serial port (auto-detected)")
    ap.add_argument("--model", default=None, help="path to the vosk model")
    ap.add_argument("--save", default=None, help="write each command to this WAV")
    ap.add_argument("--program", default=PICO_PROGRAM,
                    help="the MicroPython program to run on the board")
    args = ap.parse_args()

    port = args.port
    if port is None:
        found = sorted(glob.glob("/dev/cu.usbmodem*")) or sorted(glob.glob("/dev/ttyACM*"))
        if not found:
            sys.exit("no Pico found; pass --port")
        port = found[0]

    model_dir = args.model
    if model_dir is None:
        found = sorted(glob.glob(MODEL_GLOB))
        if not found:
            sys.exit("no vosk model in models/ -- see the setup notes at the "
                     "top of this file")
        model_dir = found[0]

    with open(args.program) as f:
        source = f.read()

    print("port  : %s" % port)
    print("model : %s" % os.path.basename(model_dir))
    print("board : %s" % os.path.basename(args.program))
    print("loading recognizer...")
    rec = load_recognizer(model_dir, ASR_RATE)
    print("starting the program on the Pico. Ctrl-C to stop.")
    print("-" * 62)

    ser = serial.Serial(port, 115200, timeout=0.2)
    start_program(ser, source)

    # ONE buffer and a mode flag, deliberately.
    #
    # The obvious structure -- print lines until you see the header, then call
    # a function that reads the audio -- does not work here, and fails in a way
    # that looks like a timeout. A single 512-byte read routinely contains the
    # header AND the first base64 lines, so the reader starts mid-stream while
    # the bytes it needed sit in the caller's buffer. Keeping one buffer and
    # switching modes on the marker lines removes the seam entirely.
    buf = b""
    mode = "normal"
    b64 = []
    rate = 12800
    samples = 0
    try:
        while True:
            chunk = ser.read(512)
            if chunk:
                buf += chunk
            while b"\n" in buf:
                one, buf = buf.split(b"\n", 1)
                text = one.decode("utf-8", "replace").replace("\x04", "").strip()
                # Strip the REPL's '>' prompt from the LEFT only. Stripping it
                # from both ends -- which is the obvious thing to write -- eats
                # the trailing '>>>' of the <<<END>>> marker, so the terminator
                # never matches, the reader collects audio forever and the
                # whole exchange looks like the board went silent. Nothing
                # legitimate on this line starts with '>': the markers begin
                # with '<' and base64 has no '>' in its alphabet at all.
                while text.startswith(">"):
                    text = text[1:].lstrip()
                if not text:
                    continue
                if mode == "normal":
                    if text.startswith(HDR):
                        m = re.search(r"rate=(\d+).*?samples=(\d+)", text)
                        rate = int(m.group(1)) if m else 12800
                        samples = int(m.group(2)) if m else 0
                        b64 = []
                        mode = "audio"
                    else:
                        print("pico | %s" % text)
                else:
                    if text == FTR:
                        finish(ser, b"".join(b64), rate, samples, rec, args.save)
                        mode = "normal"
                    else:
                        try:
                            b64.append(base64.b64decode(text))
                        except Exception:
                            pass          # REPL noise on the line; skip it
    except KeyboardInterrupt:
        print()
        print("stopping.")
    finally:
        ser.write(b"\r\x03\x03\r\x02")     # interrupt, then friendly REPL
        ser.close()


def finish(ser, pcm, rate, samples, rec, save_path):
    got = len(pcm) // 2
    print("  audio: %d samples (%.2f s)%s"
          % (got, got / rate, "" if got == samples else "  [expected %d]" % samples))

    if save_path:
        with wave.open(save_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        print("  saved: %s" % save_path)

    audio = np.frombuffer(pcm, dtype="<i2")
    text = recognize(rec, resample(audio, rate, ASR_RATE).tobytes())
    print('  heard: "%s"' % text)

    parsed = parse_timer(text)
    if parsed is None:
        reply = "SORRY not understood"
        print("  reply: (no timer found)")
    else:
        seconds, spoken = parsed
        reply = "TIMER %d %s" % (seconds, spoken)
        print("  reply: %s  (%d s)" % (spoken, seconds))
    ser.write(reply.encode() + b"\r\n")


if __name__ == "__main__":
    main()
