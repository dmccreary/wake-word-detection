# Lab 4: Wake Word Test -- listen continuously, and say so when you hear it.
#
# This is the whole point of the kit, at its smallest honest size. The
# microphone streams without stopping, every frame becomes a spectrum, and a
# rolling window of those spectra is compared against a phrase you enrolled
# yourself. When the match is good enough, the display says so.
#
# It is a template-correlation detector, not a neural network. That is a
# deliberate choice: it uses nothing you have not already built, it needs no
# training toolchain, and its every decision is inspectable. It is also
# genuinely worse than a trained model, which is a finding worth measuring
# rather than a limitation worth hiding.
#
# HOW IT WORKS
#   1. Read 256 samples (20 ms of sound) off the mic. This never stops.
#   2. Window, FFT, and collapse 128 bins into 12 log-spaced band energies.
#   3. Normalize that band vector, so loud and quiet speech look the same.
#   4. Push it into a ring buffer of the last 32 frames (640 ms).
#   5. Score the ring buffer against the enrolled template: the mean dot
#      product, frame by frame. Both vectors are unit length, so a perfect
#      match scores 1.0.
#   6. Above threshold, and loud enough to be speech at all -> WAKE.
#
# CONTROLS -- the kit has two buttons, MODE and SELECT.
#   MODE    cycles LISTEN -> ENROLL -> FORGET -> LISTEN
#   SELECT  in LISTEN: raise the threshold one step. It WRAPS: past
#                      THRESHOLD_MAX it returns to THRESHOLD_MIN, which is how
#                      one button covers a range that used to need two.
#           in ENROLL: record one repetition of your phrase
#           in FORGET: discard every enrollment and start over
#
# FORGET is its own mode rather than a long-press because throwing away an
# enrollment you spent a minute recording should take a deliberate walk through
# the mode list, not a mistimed hold.

import math
import struct
import time

import config
import fft_asm

N = 256                                  # samples per frame
FRAME_MS = N / config.SAMPLE_RATE * 1000  # 20.0 ms of sound per frame

BANDS = 12                               # band energies per frame
BAND_LO_HZ = 150
BAND_HI_HZ = 6000

# The reference wake phrase for this course is "Hey Pico" (see the lab writeup
# for why). The original 800 ms here was an estimate -- "said deliberately it
# runs 800-900 ms" -- and the first hardware session showed the phrase is
# clearly shorter than that at a natural pace. 640 ms is a conservative trim,
# not a fitted value: see the note in enroll() for why the fill percentage
# that first suggested it could not be trusted, and re-measure with the
# repaired metric before tightening this further.
#
# Padding is not harmless. Every frame is mean-subtracted and L2-normalized, so
# a SILENT frame still emits a unit vector -- one pointing along whatever the
# room's noise spectrum happens to be. Steady noise (a furnace fan, in the room
# this was measured in) is highly repeatable, so those padding frames match
# each other almost perfectly and inflate the score with agreement about the
# ROOM rather than about the phrase. Sizing the window to the phrase is what
# stops the detector from grading itself on silence.
#
# This is not free -- but here the change runs the good way. Scoring costs
# TEMPLATE_FRAMES * BANDS float multiply-adds EVERY frame, and a MicroPython
# float multiply is ~1,097 cycles. At 32 frames that is 384 multiply-adds,
# roughly 3.5 ms of the 20 ms budget, down from 4.4 ms at 40. Raising this is
# still the first thing to suspect if the overrun counter starts moving.
TEMPLATE_FRAMES = 32                     # 640 ms -- fits a 3-syllable phrase

# A starting point, not a right answer.
#
# This number was chosen from a measurement, not taste. A fixed-length template
# has no time warping, so the score falls off sharply when the phrase is spoken
# at a different pace than it was enrolled at. Measured on synthetic speech,
# against an enrollment that filled the whole window. The relationship is one
# of FILL FRACTION, so it survived the window shrinking from 800 ms to 640 ms
# -- only the millisecond column below was rescaled, the scores are as
# measured:
#
#     phrase fills 100% of window (640 ms) -> 0.97
#                   95%           (608 ms) -> 0.84
#                   90%           (576 ms) -> 0.77
#                   85%           (544 ms) -> 0.66
#                   80%           (512 ms) -> 0.49
#     a phrase using the same sounds in a different order -> 0.52
#
# So the threshold has to sit above ~0.52 to reject an impostor, but low enough
# to accept the enrolled speaker varying their pace by the +/-10% a human
# naturally does. 0.70 accepts down to about 88% fill and still clears the
# impostor by ~0.18. At 0.80 a perfectly good utterance said 10% quickly is
# rejected, which is why the obvious-looking higher number is the wrong one.
THRESHOLD_START = 0.70
THRESHOLD_STEP = 0.01

# With one button the threshold can only travel in one direction, so the range
# is a loop: step past the top and it comes back at the bottom. The bounds are
# the same ones the old two-button version clamped to.
THRESHOLD_MIN = 0.30
THRESHOLD_MAX = 0.99

# A normalized silence spectrum can match another normalized silence spectrum
# almost perfectly, so score alone is not enough -- the frame has to be loud
# enough to be speech in the first place. This gate is what stops a quiet room
# from triggering constantly.
#
# The value lives in config.py because it is MEASURED, not chosen: Lab 3
# (Microphone Calibration) characterizes your room and your speaking distance and prints the number to
# put there. Running this lab on the default without calibrating first is the
# single most common reason the detector "cannot hear you".
SPEECH_FLOOR = config.SPEECH_FLOOR

# After a detection, ignore everything for a moment. Without this, one spoken
# phrase fires on every frame it stays inside the window.
REFRACTORY_MS = 1500

DISPLAY_EVERY = 8                        # redraw every 8 frames (~160 ms)

PROGRAM = "04-wake-word-test"
VERSION = "1.4.0"               # 1.4.0: speaker preallocated; 32-frame window

MODE_LISTEN = 0
MODE_ENROLL = 1
MODE_FORGET = 2
MODE_NAMES = ["LISTEN", "ENROLL", "FORGET"]

oled = config.init_display()
button_mode, button_select = config.init_buttons()
mic = config.init_microphone()
led = config.init_led()

# The speaker is opened ONCE, here, and never from inside the detect path.
#
# init_speaker() asks for a 20,000-byte I2S buffer. Taking that at detection
# time fails with MemoryError even though the heap has ~475 KB free, which
# looks impossible until you count allocations: feature_frame() slices `raw`
# and unpacks a 256-element tuple on every one of the 50 frames per second, so
# after a short listen the heap is a minefield of small holes and no
# contiguous 20 KB survives anywhere in it. Claiming the buffer at startup,
# while the heap is still unfragmented, sidesteps the whole problem. This is
# the same lesson as the precomputed window and band edges below, learned the
# expensive way.
#
# The mic is on I2S 0 and the speaker on I2S 1 -- separate peripherals -- so
# both can stay open at once. A note for anyone extending this lab: if you add
# code that writes a FILE here (saving a template, say), both must be
# deinit()ed first and reopened after. Writing flash with any I2S peripheral
# live hard-faults the chip, with no traceback and no recovery short of
# pulling the USB cable.
speaker = config.init_speaker()

# The amplifier's shutdown pin, which this lab previously never touched -- so
# even before the MemoryError, a detection would very likely have beeped into
# a disabled amp and made no sound at all. The returned Pin is bound to a name
# rather than discarded on purpose: keeping a reference is the habit that stops
# an enable line from being a mystery later.
amp = config.init_amp_enable()

# The beep waveform is built once too, for the same reason -- play_tone() would
# otherwise allocate a fresh ~3.8 KB buffer on every detection.
beep = config.tone_buffer(1320, 120)

fft = fft_asm.FFT(N)
re, im = fft.make_buffers()
raw = bytearray(N * 4)

# Hann window, precomputed once. Without it, a phrase that starts mid-frame
# smears energy across every band and the template match degrades badly.
window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]

# Log-spaced band edges, in FFT bin numbers. Speech energy is not spread evenly
# across frequency, so neither are the bands: low bands are narrow, high bands
# are wide, which is the same reasoning behind a mel scale.
bin_hz = config.SAMPLE_RATE / N
lo_bin = max(1, int(BAND_LO_HZ / bin_hz))
hi_bin = min(N // 2 - 1, int(BAND_HI_HZ / bin_hz))
ratio = (hi_bin / lo_bin) ** (1.0 / BANDS)
edges = [int(lo_bin * (ratio ** b)) for b in range(BANDS + 1)]
for b in range(BANDS):
    if edges[b + 1] <= edges[b]:
        edges[b + 1] = edges[b] + 1

# Ring buffer of the last TEMPLATE_FRAMES feature vectors, plus their loudness.
ring = [[0.0] * BANDS for _ in range(TEMPLATE_FRAMES)]
ring_rms = [0.0] * TEMPLATE_FRAMES
ring_pos = 0
frames_seen = 0

# The enrolled template: a running sum of enrollments, averaged on use.
template_sum = [[0.0] * BANDS for _ in range(TEMPLATE_FRAMES)]
template = None
enrollments = 0

mode = MODE_LISTEN
threshold = THRESHOLD_START
score = 0.0
detections = 0
last_detect_ms = 0
banner_until_ms = 0

# Honest self-measurement, in the spirit of the prerequisite course: if a frame
# takes longer to process than it took to record, audio is being dropped.
worst_frame_ms = 0.0
overruns = 0

# Latched by interrupt, not polled: enroll() blocks while it records a
# template, and a press made during it would never be seen as an edge at all.
# See config.latch_buttons().
took, poll_buttons = config.latch_buttons(button_mode, button_select)


def feature_frame():
    """Read one frame off the mic and return (unit band vector, rms).

    This is the only place that touches the microphone, and it is called in a
    tight loop -- everything expensive is precomputed outside it.
    """
    n = mic.readinto(raw)
    count = n // 4

    # '<' little-endian, 'i' signed 32-bit. The INMP441 packs 24 bits of audio
    # into the top of each word, so every sample gets shifted right by 8.
    words = struct.unpack("<%di" % count, raw[:count * 4])

    total = 0
    for w in words:
        total += w >> 8
    dc = total / count

    energy = 0.0
    for i in range(N):
        s = ((words[i] >> 8) - dc) if i < count else 0.0
        energy += s * s
        re[i] = s * window[i]
        im[i] = 0.0
    rms = math.sqrt(energy / N)

    fft.run(re, im)

    # Band energies. Power, not magnitude -- no sqrt per bin, and the log
    # afterwards flattens the difference anyway.
    vec = [0.0] * BANDS
    for b in range(BANDS):
        acc = 0.0
        for k in range(edges[b], edges[b + 1]):
            acc += re[k] * re[k] + im[k] * im[k]
        # log compression: speech spans a huge dynamic range, and the quiet
        # bands carry as much identity as the loud ones.
        vec[b] = math.log(1.0 + acc / (edges[b + 1] - edges[b]))

    # Subtract the frame's mean log-energy. This step is not optional, and
    # leaving it out is a genuinely instructive failure: raw log energies all
    # land within a few percent of each other (around 25-28 for ordinary
    # speech), so every normalized vector ends up pointing in almost the same
    # direction and EVERYTHING scores ~1.00 -- silence included. Removing the
    # common offset is what leaves only the spectral SHAPE behind, which is the
    # part that actually identifies a phrase. Real MFCC pipelines do the same
    # thing under the name cepstral mean normalization.
    mean = 0.0
    for b in range(BANDS):
        mean += vec[b]
    mean /= BANDS
    for b in range(BANDS):
        vec[b] -= mean

    # L2 normalize, so the same phrase said loudly and softly gives the same
    # vector. This is what makes the dot product below a similarity score.
    norm = 0.0
    for b in range(BANDS):
        norm += vec[b] * vec[b]
    norm = math.sqrt(norm)
    if norm > 0:
        for b in range(BANDS):
            vec[b] /= norm
    return vec, rms


def push(vec, rms):
    global ring_pos, frames_seen
    ring[ring_pos] = vec
    ring_rms[ring_pos] = rms
    ring_pos = (ring_pos + 1) % TEMPLATE_FRAMES
    frames_seen += 1


def window_score():
    """Mean per-frame dot product between the ring buffer and the template.

    The ring buffer is read oldest-first starting at ring_pos, so frame f of
    the template lines up with the frame that arrived f slots ago.
    """
    if template is None or frames_seen < TEMPLATE_FRAMES:
        return 0.0
    total = 0.0
    for f in range(TEMPLATE_FRAMES):
        live = ring[(ring_pos + f) % TEMPLATE_FRAMES]
        ref = template[f]
        acc = 0.0
        for b in range(BANDS):
            acc += live[b] * ref[b]
        total += acc
    return total / TEMPLATE_FRAMES


def window_rms():
    """Loudest frame in the current window -- the speech-present gate."""
    return max(ring_rms)


def rebuild_template():
    """Average the enrollments, then re-normalize each averaged frame."""
    global template
    if enrollments == 0:
        template = None
        return
    built = []
    for f in range(TEMPLATE_FRAMES):
        vec = [template_sum[f][b] / enrollments for b in range(BANDS)]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        built.append(vec)
    template = built


def enroll():
    """Record one repetition of the phrase into the template."""
    global enrollments

    for count in (3, 2, 1):
        oled.fill(config.BLACK)
        oled.text("ENROLL", 40, 4, config.WHITE)
        oled.text("Say it in %d" % count, 16, 28, config.WHITE)
        oled.show()
        for _ in range(7):      # keep buttons responsive through the countdown
            poll_buttons()
            time.sleep_ms(100)

    oled.fill(config.BLACK)
    oled.text("SPEAK NOW", 28, 24, config.WHITE)
    oled.show()

    # Flush whatever accumulated in the mic's buffer during the countdown, so
    # enrollment starts with sound recorded from this instant forward.
    #
    # The WHOLE buffer, not one frame. config.MIC_BUFFER_BYTES is 40000 bytes
    # -- 781 ms of audio -- and nothing has read the mic during the 2.1 s
    # countdown, so it is full. Discarding a single 20 ms frame would leave the
    # click of the button you just pressed sitting at the front of the
    # recording, baked into the template as if it were part of your phrase.
    for _ in range(config.MIC_BUFFER_BYTES // len(raw) + 4):
        mic.readinto(raw)

    # Nothing is drawn during the capture loop on purpose. An OLED update takes
    # several milliseconds over SPI, which would blow the 20 ms frame deadline
    # and drop audio -- corrupting the very template we are recording.
    frame_level = [0.0] * TEMPLATE_FRAMES
    for f in range(TEMPLATE_FRAMES):
        vec, rms = feature_frame()
        frame_level[f] = rms
        for b in range(BANDS):
            template_sum[f][b] += vec[b]

    enrollments += 1
    rebuild_template()

    # How many frames did the phrase actually occupy? Measured against THIS
    # recording's own peak, not against SPEECH_FLOOR.
    #
    # Gating on SPEECH_FLOOR here was a real bug, and one that concealed
    # itself: if the floor sits below the room's noise, silence counts as
    # speech and every phrase reads longer than it is. That is not a
    # hypothetical. The first hardware run used the uncalibrated default of
    # 6711, while the same room's MEDIAN noise frame measured 7221 -- so more
    # than half of all silence scored as speech, fill reported 72-82%, and the
    # phrase looked like it nearly filled an 800 ms window when it did not
    # come close. A peak-relative gate cannot make that particular mistake,
    # because it has no absolute number in it to get wrong.
    #
    # -6 dB below peak is deliberately generous; a tighter gate would clip the
    # quiet consonants at the edges of the phrase. The honest caveat is that
    # this still needs the phrase to clear the room noise by more than 6 dB.
    # If fill reads high when you say nothing at all, that is the room being
    # measured, not your pace -- and the fix is a quieter room or the
    # band-limited energy gate, not a different number here.
    peak = max(frame_level)
    gate = peak * 0.5
    speech_frames = 0
    for f in range(TEMPLATE_FRAMES):
        if frame_level[f] > gate:
            speech_frames += 1

    # This is the single most useful number to show a student, because a
    # fixed-length template has no time warping: a phrase that fills 80% of the
    # window scores about 0.49 against one enrolled at 100%, which is below the
    # impostor score. Pace consistency is not a nicety here, it is the whole
    # ballgame.
    fill = speech_frames * 100 // TEMPLATE_FRAMES

    oled.fill(config.BLACK)
    oled.text("Recorded", 32, 4, config.WHITE)
    oled.text("%d sample(s)" % enrollments, 16, 18, config.WHITE)
    oled.text("fill %d%%" % fill, 0, 34, config.WHITE)
    if fill < 85:
        oled.text("say it SLOWER", 0, 46, config.WHITE)
    elif fill > 99:
        oled.text("say it QUICKER", 0, 46, config.WHITE)
    else:
        oled.text("good pace", 0, 46, config.WHITE)
    oled.show()
    time.sleep_ms(1200)
    print("enrolled sample %d  (window fill %d%%)" % (enrollments, fill))
    if fill < 85:
        print("  -> phrase is short for this window; say it more deliberately")
        print("     or lower TEMPLATE_FRAMES (now %d = %d ms) to match your pace"
              % (TEMPLATE_FRAMES, TEMPLATE_FRAMES * FRAME_MS))


def forget():
    global enrollments, template
    for f in range(TEMPLATE_FRAMES):
        for b in range(BANDS):
            template_sum[f][b] = 0.0
    enrollments = 0
    template = None
    print("enrollments cleared")


def announce():
    """Beep on detection.

    Note what this costs: while write() blocks, the microphone's DMA keeps
    filling its buffer with the beep itself. We flush that audio afterwards so
    the detector does not immediately match on its own noise. That is the
    crudest possible form of the self-trigger problem -- and mute-and-resume is
    the crudest possible fix. A real assistant playing a full spoken sentence
    needs considerably more than this.

    The speaker and the waveform are both allocated at startup, not here --
    see the note at the top. Nothing in this function allocates, which is the
    only reason it can be called from the detect path at all.
    """
    speaker.write(beep)
    mic.readinto(raw)


def draw():
    oled.fill(config.BLACK)

    if time.ticks_diff(banner_until_ms, time.ticks_ms()) > 0:
        oled.fill_rect(0, 0, config.WIDTH, 34, config.WHITE)
        oled.text("WAKE WORD", 20, 8, config.BLACK)
        oled.text("DETECTED", 24, 20, config.BLACK)
        oled.text("score %.2f" % score, 0, 40, config.WHITE)
        oled.text("count %d" % detections, 0, 52, config.WHITE)
        oled.show()
        return

    oled.text("Lab 4: " + MODE_NAMES[mode], 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)

    if mode == MODE_ENROLL:
        oled.text("samples: %d" % enrollments, 0, 16, config.WHITE)
        oled.text("SELECT = record", 0, 30, config.WHITE)
        oled.text("MODE   = next", 0, 52, config.WHITE)
        oled.show()
        return

    if mode == MODE_FORGET:
        oled.text("samples: %d" % enrollments, 0, 16, config.WHITE)
        oled.text("Discard the", 0, 28, config.WHITE)
        oled.text("enrollment?", 0, 38, config.WHITE)
        oled.text("SELECT = yes", 0, 52, config.WHITE)
        oled.show()
        return

    if template is None:
        oled.text("No wake word", 0, 20, config.WHITE)
        oled.text("enrolled yet.", 0, 30, config.WHITE)
        oled.text("MODE to enroll", 0, 48, config.WHITE)
        oled.show()
        return

    oled.text("score %.2f" % score, 0, 16, config.WHITE)
    oled.text("thresh %.2f" % threshold, 0, 26, config.WHITE)

    # Score bar, with a tick showing where the threshold sits.
    oled.rect(0, 38, config.WIDTH, 10, config.WHITE)
    filled = int(max(0.0, min(1.0, score)) * (config.WIDTH - 4))
    if filled > 0:
        oled.fill_rect(2, 40, filled, 6, config.WHITE)
    tick = 2 + int(threshold * (config.WIDTH - 4))
    oled.vline(tick, 36, 14, config.WHITE)

    oled.text("hits %d" % detections, 0, 52, config.WHITE)
    if overruns:
        oled.text("OVR %d" % overruns, 80, 52, config.WHITE)
    oled.show()


print("%s v%s  (config v%s)" % (PROGRAM, VERSION, config.CONFIG_VERSION))
print("Lab 4: Wake Word Test")
print("frame = %d samples = %.1f ms; window = %d frames = %d ms"
      % (N, FRAME_MS, TEMPLATE_FRAMES, int(TEMPLATE_FRAMES * FRAME_MS)))
print("bands = %d, bins %d..%d" % (BANDS, edges[0], edges[-1]))
print()
print("BUTTONS:  MODE (GPIO %d) cycles LISTEN -> ENROLL -> FORGET"
      % config.BUTTON_MODE_PIN)
print("          SELECT (GPIO %d) acts on the current mode:"
      % config.BUTTON_SELECT_PIN)
print("            LISTEN  raise threshold one step (wraps %.2f -> %.2f)"
      % (THRESHOLD_MAX, THRESHOLD_MIN))
print("            ENROLL  record one repetition of your phrase")
print("            FORGET  discard every enrollment")
print()
print("Enroll your phrase 3-5 times, then MODE back round to LISTEN.")
print()

# Settle the microphone: the first reads after power-up are garbage.
for _ in range(5):
    mic.readinto(raw)
    time.sleep_ms(20)

draw()
frame_count = 0

try:
    while True:
        now = time.ticks_ms()

        if took("mode"):
            mode = (mode + 1) % len(MODE_NAMES)
            frames_seen = 0                    # window is stale after a mode change
            print("mode ->", MODE_NAMES[mode])
            draw()

        elif took("select"):
            if mode == MODE_ENROLL:
                enroll()
                frames_seen = 0
            elif mode == MODE_FORGET:
                forget()
            else:
                # Rounded, not accumulated: adding 0.01 repeatedly to a float
                # drifts, and a threshold printed as 0.7999999 is a bug report
                # waiting to happen. Wraps at the top -- one button cannot walk
                # back down.
                threshold = round(threshold + THRESHOLD_STEP, 2)
                if threshold > THRESHOLD_MAX:
                    threshold = THRESHOLD_MIN
                print("threshold ->", threshold)
            draw()

        # Neither ENROLL nor FORGET runs the detector -- both just wait for a
        # button, so there is no reason to spend a frame time on the FFT.
        if mode != MODE_LISTEN:
            time.sleep_ms(20)
            continue

        # --- the real-time path -------------------------------------------
        # Everything below runs once per frame, forever, and must finish in
        # less than FRAME_MS or audio is lost.
        t0 = time.ticks_us()

        vec, rms = feature_frame()
        push(vec, rms)

        if template is not None:
            score = window_score()

            quiet = time.ticks_diff(now, last_detect_ms) > REFRACTORY_MS
            loud_enough = window_rms() > SPEECH_FLOOR
            ready = frames_seen >= TEMPLATE_FRAMES

            if ready and quiet and loud_enough and score >= threshold:
                detections += 1
                last_detect_ms = now
                banner_until_ms = time.ticks_add(now, 1200)
                led.on()
                print("WAKE WORD DETECTED  score=%.3f  rms=%.0f  #%d"
                      % (score, window_rms(), detections))
                draw()
                announce()
                led.off()
                frames_seen = 0                # do not re-fire on the same audio

        # Processing time excludes the readinto() wait, which IS the frame's
        # own duration -- what matters is whether the work after it fits.
        frame_ms = time.ticks_diff(time.ticks_us(), t0) / 1000.0 - FRAME_MS
        if frame_ms > worst_frame_ms:
            worst_frame_ms = frame_ms
        if frame_ms > FRAME_MS:
            overruns += 1

        frame_count += 1
        if frame_count % DISPLAY_EVERY == 0:
            draw()

except KeyboardInterrupt:
    mic.deinit()
    speaker.deinit()
    oled.fill(config.BLACK)
    oled.text("Stopped.", 30, 20, config.WHITE)
    oled.text("hits: %d" % detections, 30, 36, config.WHITE)
    oled.show()
    print()
    print("Stopped after %d frames." % frame_count)
    print("detections      : %d" % detections)
    print("worst frame work: %.2f ms (budget %.1f ms)" % (worst_frame_ms, FRAME_MS))
    print("frame overruns  : %d" % overruns)
    if overruns:
        print()
        print("Overruns mean audio was dropped. The detector still 'works',")
        print("but its measured miss rate is now partly a timing artifact --")
        print("fix the budget before trusting any accuracy number from it.")
