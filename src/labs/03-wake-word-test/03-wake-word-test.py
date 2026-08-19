# Lab 3: Wake Word Test -- listen continuously, and say so when you hear it.
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
# CONTROLS
#   MODE  cycles LISTEN -> ENROLL -> LISTEN
#   UP    in LISTEN: raise the threshold (stricter, fewer false accepts)
#         in ENROLL: record one repetition of your phrase
#   DOWN  in LISTEN: lower the threshold (looser, fewer false rejects)
#         in ENROLL: forget every enrollment and start over

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
# for why). Said deliberately it runs 800-900 ms, so the window has to be at
# least that long or enrollment clips the tail of "-co".
#
# This is not free. Scoring costs TEMPLATE_FRAMES * BANDS float multiply-adds
# EVERY frame, and a MicroPython float multiply is ~1,097 cycles. At 40 frames
# that is 480 multiply-adds, roughly 4.4 ms of the 20 ms budget. Raising this
# further is the first thing to suspect if the overrun counter starts moving.
TEMPLATE_FRAMES = 40                     # 800 ms -- fits a 3-syllable phrase

# A starting point, not a right answer. On synthetic speech this detector
# scores ~0.97 for the enrolled phrase and ~0.5 for a phrase built from the
# same sounds in a different order, so 0.80 sits sensibly between them. Real
# speech in a real room is messier -- tuning this with UP/DOWN, and watching
# what it does to false accepts versus false rejects, is the actual exercise.
THRESHOLD_START = 0.80
THRESHOLD_STEP = 0.01

# A normalized silence spectrum can match another normalized silence spectrum
# almost perfectly, so score alone is not enough -- the frame has to be loud
# enough to be speech in the first place. This gate is what stops a quiet room
# from triggering constantly.
SPEECH_FLOOR = config.FULL_SCALE * 0.004

# After a detection, ignore everything for a moment. Without this, one spoken
# phrase fires on every frame it stays inside the window.
REFRACTORY_MS = 1500

DISPLAY_EVERY = 8                        # redraw every 8 frames (~160 ms)

MODE_LISTEN = 0
MODE_ENROLL = 1
MODE_NAMES = ["LISTEN", "ENROLL"]

oled = config.init_display()
button_mode, button_up, button_down = config.init_buttons()
mic = config.init_microphone()
led = config.init_led()

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

last = [button_mode.value(), button_up.value(), button_down.value()]
last_press_ms = time.ticks_ms()


def pressed(pin, previous):
    return previous == 1 and pin.value() == 0


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
        time.sleep_ms(700)

    oled.fill(config.BLACK)
    oled.text("SPEAK NOW", 28, 24, config.WHITE)
    oled.show()

    # Flush whatever accumulated in the mic's buffer during the countdown, so
    # enrollment starts with sound recorded from this instant forward.
    mic.readinto(raw)

    for f in range(TEMPLATE_FRAMES):
        vec, _ = feature_frame()
        for b in range(BANDS):
            template_sum[f][b] += vec[b]

    enrollments += 1
    rebuild_template()

    oled.fill(config.BLACK)
    oled.text("Recorded", 32, 20, config.WHITE)
    oled.text("%d sample(s)" % enrollments, 16, 36, config.WHITE)
    oled.show()
    time.sleep_ms(800)
    print("enrolled sample %d" % enrollments)


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
    """
    speaker = config.init_speaker()
    config.play_tone(speaker, 1320, 120, config.DEFAULT_VOLUME)
    speaker.deinit()
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

    oled.text("Lab 3: " + MODE_NAMES[mode], 0, 0, config.WHITE)
    oled.hline(0, 10, config.WIDTH, config.WHITE)

    if mode == MODE_ENROLL:
        oled.text("samples: %d" % enrollments, 0, 16, config.WHITE)
        oled.text("UP   = record", 0, 30, config.WHITE)
        oled.text("DOWN = forget", 0, 40, config.WHITE)
        oled.text("MODE = listen", 0, 52, config.WHITE)
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


print("Lab 3: Wake Word Test")
print("frame = %d samples = %.1f ms; window = %d frames = %d ms"
      % (N, FRAME_MS, TEMPLATE_FRAMES, int(TEMPLATE_FRAMES * FRAME_MS)))
print("bands = %d, bins %d..%d" % (BANDS, edges[0], edges[-1]))
print()
print("MODE cycles LISTEN/ENROLL. Enroll your phrase 3-5 times, then listen.")
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
        settled = time.ticks_diff(now, last_press_ms) > config.DEBOUNCE_MS

        if settled and pressed(button_mode, last[0]):
            mode = MODE_ENROLL if mode == MODE_LISTEN else MODE_LISTEN
            last_press_ms = now
            frames_seen = 0                    # window is stale after a mode change
            print("mode ->", MODE_NAMES[mode])
            draw()

        elif settled and pressed(button_up, last[1]):
            last_press_ms = now
            if mode == MODE_ENROLL:
                enroll()
                frames_seen = 0
            else:
                threshold = min(0.99, threshold + THRESHOLD_STEP)
                print("threshold ->", threshold)
            draw()

        elif settled and pressed(button_down, last[2]):
            last_press_ms = now
            if mode == MODE_ENROLL:
                forget()
            else:
                threshold = max(0.30, threshold - THRESHOLD_STEP)
                print("threshold ->", threshold)
            draw()

        last = [button_mode.value(), button_up.value(), button_down.value()]

        if mode == MODE_ENROLL:
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
