---
title: "Appendix A: Parts List and Cost"
description: Every component in the smart speaker kit, what each one costs at three purchasing tiers, and the buying decisions that change the total
---

# Appendix A: Parts List and Cost

## The Short Answer

**A complete kit costs about $26 to $48 per student**, depending on how you buy.

| How you buy | Per-kit cost |
|---|---|
| **Classroom** — multipacks split across ~20 students | **≈ $26** |
| **Single kit** — one of everything from a general marketplace | **$36–48** (≈ $41 typical) |
| **Named-brand** — Adafruit, SparkFun, Pi Hut equivalents | **≈ $58** |

Use **$36** as a planning figure for a single kit.

The single-kit column is a genuine range, not a fuzzy estimate: **$35.50** if every part comes in
at the low end and **$47.50** if every part comes in at the high end. Which end you land on is
decided mostly by two line items — **the display and the board** — so those are the two worth
shopping for.

The display is also the one place where a deliberate choice raises the total: this kit specifies a
**2.42-inch** OLED rather than the common 0.96" or 1.3", which costs about **$5 more** and is worth
it. [See below](#why-the-242-display-and-what-it-costs) — and if budget is tight, the smaller
display is a genuine drop-in that changes no code.

!!! warning "Prices checked August 2026 — treat them as estimates"
    Only the Raspberry Pi Pico 2 W has a genuine list price ($7.00, set by Raspberry Pi). Every
    other component is a commodity part sold by dozens of vendors at prices that move constantly
    and depend heavily on pack size. The ranges below are what you should *expect to budget*, not
    quotes.

## Complete Parts List

| # | Component | Qty | First used | Classroom | Single kit | Named-brand |
|---|---|---|---|---|---|---|
| 1 | Raspberry Pi Pico 2 **W** (RP2350 + wireless) | 1 | Lab 1 | $7.00 | $7.00–10.00 | $7.00 |
| 2 | **2.42"** SSD1306/SSD1309 128×64 OLED, **SPI** | 1 | Lab 1 | $8.00 | $10.00–13.00 | $20.00 § |
| 3 | INMP441 I²S MEMS microphone | 1 | Lab 1 | $2.00 | $3.50–4.50 | $6.95 † |
| 4 | MAX98357A I²S class-D amplifier | 1 | Lab 1 | $2.50 | $4.00–5.00 | $5.95 ‡ |
| 5 | Speaker, 8 Ω, 2–3 W | 1 | Lab 1 | $1.50 | $2.00–3.00 | $1.95 |
| 6 | Momentary push buttons | 3 | Lab 1 | $0.30 | $1.00 | $2.50 |
| 7 | Breadboard + jumper wires | 1 set | Lab 1 | $4.00 | $6.00–8.00 | $10.90 |
| 8 | USB cable (board to computer) | 1 | Lab 1 | $1.00 | $2.00–3.00 | $2.95 |
| | **Total** | | | **$26.30** | **$35.50–47.50** | **$58.20** |

† Adafruit and SparkFun do not stock the INMP441; the named-brand column substitutes Adafruit's
SPH0645 I²S microphone, which is pin-compatible in spirit but **not** in wiring. If you use it,
the pin numbers in `config.py` still apply but check the breakout's own labelling.

‡ [Adafruit $5.95](https://www.adafruit.com/product/3006), [SparkFun
$7.50](https://www.sparkfun.com/sparkfun-i2s-audio-breakout-max98357a.html).

§ Neither Adafruit nor SparkFun stocks a 2.42" module, so the named-brand column uses a specialty
display vendor. The 2.42" is largely an overseas-marketplace part.

## Why the 2.42" Display, and What It Costs

**Buy the 2.42-inch display if you can.** It is the single most expensive optional upgrade in the
kit — roughly **$5 more** than the 1.3" version and more again over the common 0.96" — and it is
the one worth paying for in this course.

| Diagonal | Typical single-unit price | Verdict |
|---|---|---|
| 0.96" | $3–5 | Works, but you will lean in to read it |
| 1.3" | $4–7 | Acceptable |
| **2.42"** | **$9–13** | **Preferred** |

The reason is specific to what this kit *is*. A spectrum analyzer sits on a bench and you look at
it from 30 cm. A smart speaker sits in a room and you glance at it from across that room — and
Lab 4 in particular asks you to watch a live score bar while speaking at a realistic distance,
which is exactly the situation a 0.96" display handles badly.

!!! tip "The upgrade costs nothing but money"
    All three sizes are **128×64 pixels** with the same SPI pinout and the same driver. The 2.42"
    module is physically larger with the same resolution, so **not one line of code changes** —
    `config.py` is identical, and every lab runs unmodified. You are buying legibility, not
    capability.

!!! note "SSD1306 vs SSD1309"
    2.42" modules are frequently built around the **SSD1309** controller rather than the SSD1306.
    The two are close enough that the `ssd1306.py` driver in `lib/` drives both — this is the same
    display the prerequisite course's kit used, whose `config.py` is commented
    `2.42" SSD1306/SSD1309 SPI display`. If a particular 2.42" module comes up blank, that is the
    first thing to investigate, not the wiring.

If budget forces the choice, the 1.3" is a genuine drop-in and no lab is impossible with it.
Buying twenty 0.96" displays to save $100 across a class is a false economy — you will spend it
back in students squinting at a score bar during Lab 4.

## The One Thing That Can Cost You a Soldering Iron

The prerequisite course made a point of requiring **no soldering** — five components, a breadboard,
no iron. This course adds one part that can break that promise.

!!! warning "Buy a MAX98357A with headers already attached"
    Adafruit's board explicitly ships *without* headers on: *"Comes as an assembled and tested
    breakout board with pre-soldered terminal block, with a small piece of optional header. Some
    soldering is required to attach the header."*

    Generic marketplace MAX98357A boards are usually sold **with headers pre-soldered**, and those
    are the ones to buy for this course. Check the listing photo before ordering — a board with
    bare holes means someone has to solder 6 to 8 joints per kit before Lab 1 can start.

    If you already own an iron this is a five-minute job and the Adafruit board is the better one.
    If you do not, buying the pre-soldered generic keeps the kit's no-solder property intact and
    saves you $40 on an iron you would otherwise need.

The same check applies to the INMP441 and the OLED, though both are far more commonly sold
pre-soldered.

## If You Already Did the Prerequisite Course

Most of this kit is the [Real-Time DSP on a $5
Microcontroller](https://dmccreary.github.io/fft-benchmarking/) kit you already own.

| Already have | Need to add |
|---|---|
| SSD1306 OLED | MAX98357A amplifier |
| INMP441 microphone | Speaker |
| Breadboard and jumpers | One more push button (2 → 3) |
| 2 push buttons | A Pico 2 **W**, if yours is a plain Pico 2 |
| USB cable | |

**Upgrade cost: about $4–8**, plus the board if you need one — and nothing at all for the
display, since the prerequisite course specified the same 2.42" module.

That board line deserves a precise answer, because it depends on what you already own:

- **Buying a board anyway?** The W costs **$2 more** than the plain Pico 2 ($7 vs $5).
- **Already own a plain Pico 2?** You need a second board, so it is the **full $7**. The plain
  Pico 2 is not upgradeable — the wireless radio is a separate Infineon CYW43439 chip on the W,
  not a firmware option.

Unlike the prerequisite course, where the W was optional until its final chapter, **the W is
required from Lab 1 here**, so this is not a purchase you can defer.

## Where to Buy

**Split the order in two.** The board and everything else want different vendors, for different
reasons.

| What | Buy from | Why |
|---|---|---|
| **Raspberry Pi Pico 2 W** | **Micro Center** or **DigiKey** | Authorized distributors. Genuine boards at the real $7 list price, in stock, and if you have a Micro Center nearby you can walk out with one the same day |
| **Everything else** | **eBay** | The mic, display, amplifier, speaker, buttons, breadboard, and jumpers are all commodity modules. eBay is consistently the cheapest source and sells them in the multipacks that drive the per-student cost down |

**On the board specifically.** Buy the Pico from an authorized distributor rather than a general
marketplace. Counterfeit and mislabeled RP2040/RP2350 boards do circulate, and the failure mode is
nasty here: a board sold as a "Pico 2 W" that is actually an RP2040 has no floating-point unit, so
Lab 2's assembly FFT will not run — and you will spend the afternoon suspecting your code. Micro
Center and DigiKey both remove that entire class of problem, and neither charges a premium over
list.

**On eBay for the rest.** These parts have no brand worth protecting — an INMP441 is an INMP441.
Order early, because the cheapest listings frequently ship from overseas with multi-week delivery.
For a course starting on a fixed date, order the commodity parts a month ahead or pay for the
faster domestic listings.

### Ready-made search links

The four commodity parts you will actually be shopping for. Each link is a live search — click it
and sort or filter from there.

| Part | eBay | AliExpress |
|---|---|---|
| **INMP441 microphone** | [search](https://www.ebay.com/sch/i.html?_nkw=INMP441+I2S+microphone+module&_sop=15&LH_BIN=1) | [search](https://www.aliexpress.com/w/wholesale-INMP441-microphone-module.html) |
| **MAX98357A amplifier** | [search](https://www.ebay.com/sch/i.html?_nkw=MAX98357A+I2S+amplifier+module&_sop=15&LH_BIN=1) | [search](https://www.aliexpress.com/w/wholesale-MAX98357A-I2S-amplifier.html) |
| **Breadboard + jumpers** | [search](https://www.ebay.com/sch/i.html?_nkw=830+point+breadboard+jumper+wire+kit&_sop=15&LH_BIN=1) | [search](https://www.aliexpress.com/w/wholesale-830-point-breadboard-jumper-wires-kit.html) |
| **Speaker, 8 Ω 2–3 W** | [search](https://www.ebay.com/sch/i.html?_nkw=8+ohm+2w+speaker+40mm&_sop=15&LH_BIN=1) | [search](https://www.aliexpress.com/w/wholesale-8-ohm-2W-40mm-full-range-speaker.html) |

**Tuning the search yourself.** Both sites take parameters you can append or edit:

| Site | Parameter | Effect |
|---|---|---|
| eBay | `&_sop=15` | Price + shipping, lowest first *(already in the links above)* |
| eBay | `&LH_BIN=1` | Buy It Now only, no auctions *(already applied)* |
| eBay | `&LH_PrefLoc=1` | US sellers only — add this when you need parts in days, not weeks |
| eBay | `&LH_ItemCondition=1000` | New items only |
| AliExpress | `?sortType=total_tranpro_desc` | Most orders first — the best available proxy for a listing being what it claims |
| AliExpress | `?SortType=price_asc` | Cheapest first |

For AliExpress, sorting by **order count** rather than price is usually the better move on parts
like these: a module with several hundred orders and consistent photos is a safer bet than one
that is three cents cheaper.

!!! note "What was and was not verified"
    The AliExpress link format was checked live and returns real results — the INMP441 search came
    back with modules at **$0.87–0.99 each** and a 5-pack at **$4.33**, which is *below* the
    classroom figure in the table above. The eBay links use eBay's standard, long-stable search
    URL format but could not be fetched from here (the site blocks automated requests), so they are
    constructed rather than confirmed. Click one to check it before pasting it into a syllabus.

    Prices on both sites move constantly, and the AliExpress figures exclude what is usually the
    real cost: **shipping time**. See the ordering-lead-time note above.

!!! tip "The two checks worth making on any eBay listing"
    1. **Headers pre-soldered?** Zoom in on the photo. Bare holes on the MAX98357A mean soldering
       before Lab 1 — see the section above.
    2. **The display's diagonal.** Listings bury the size. Confirm **2.42"**, not 0.96" or 1.3", if
       that is what you are paying for.

## Things People Forget

| Item | Why it matters |
|---|---|
| **USB cable** | The Pico 2 W uses **micro USB**, not USB-C. A modern laptop bag often has no micro USB cable in it |
| **A cable that carries data** | Charge-only USB cables are extremely common and produce a board that powers up and never appears to the computer. This wastes an astonishing amount of Lab 1 |
| **Spare Pico** | The most likely part to be destroyed by a wiring mistake |
| **Spare jumper wires** | They fail intermittently and are the hardest fault to diagnose |

## Notes for Instructors

**Buy multipacks on eBay, and the boards from Micro Center or DigiKey.** The INMP441, OLED,
MAX98357A, and buttons are all sold in packs of 3–5 at a
large discount, which is the single biggest lever on per-student cost — it is most of the gap
between the $26 and $36 columns. Buttons are the extreme case: a 100-pack of tactile switches
costs a few dollars and covers a class for years.

**Budget 10–15% for spares**, weighted toward Picos and jumper wires. For a class of 20 that is
roughly $80–110 on top of ~$530 in kits.

**Order the amplifier early and check the header question first.** It is the one genuinely new part
and the one most likely to arrive in a form that needs work before Lab 1.

**A note on the speaker.** The MAX98357A drives 4 Ω or 8 Ω. A 4 Ω speaker is louder for the same
supply voltage; an 8 Ω speaker draws less current, which matters when the whole board is running
off USB. Either works for every lab in this course — 8 Ω is specified simply because it is the
gentler default.

**Power the amplifier from VBUS (5 V), not 3V3.** This costs nothing but is worth saying at
purchase time, because a student who wires it to 3V3 gets a quiet, distorted amplifier and a
board that browns out mid-sentence — symptoms that look convincingly like software bugs. See
[Lab 1](../../labs/01-setup/index.md).

## Substitutions That Work

| Instead of | You can use | Caveat |
|---|---|---|
| 2.42" OLED | 1.3" or 0.96" OLED | Same 128×64, same driver, same pins — zero code changes. Saves ~$5, costs legibility |
| SSD1306 **SPI** | SSD1306 **I²C** | Cheaper and fewer wires, but slower to refresh — and `config.py` needs its display setup changed |
| SSD1306 128×64 | SH1106 128×64 | Very common lookalike; needs a different driver library |
| INMP441 | ICS-43434, SPH0645 | Any I²S MEMS mic works; check bit alignment and the L/R pin |
| MAX98357A | PCM5102 + separate amp | More parts, no benefit here |

## Substitutions That Do Not Work

Two different boards get rejected for two different reasons, and it is worth keeping them straight:

- **A plain Pico 2 (RP2350, no radio).** The chip is right and fast enough — Labs 1 through 4 all
  run on it perfectly well. It fails only from the networking labs onward, where there is no Wi-Fi.
  If you already own one, you can start the course on it and buy the W before Module 1.
- **A Pico W (RP2040).** Has the radio, wrong chip. The Cortex-M0+ has **no floating-point unit**,
  so the assembly FFT in Lab 2 cannot run and the detector cannot keep the 20 ms frame deadline.
  No amount of Wi-Fi makes up for that. This one is not a "start here and upgrade" option.
- **An analog electret microphone.** The labs assume I²S digital audio end to end; an analog mic
  would need an ADC and an entirely different capture path.
- **A USB speaker or amplifier.** The Pico 2 W cannot act as a USB audio host.

---

## Sources

Prices checked August 2026:

- [Raspberry Pi Pico 2 W on sale now at $7](https://www.raspberrypi.com/news/raspberry-pi-pico-2-w-on-sale-now/) — Raspberry Pi
- [Adafruit I²S 3W Class D Amplifier Breakout — MAX98357A](https://www.adafruit.com/product/3006) — $5.95, header soldering note
- [SparkFun I²S Audio Breakout — MAX98357A](https://www.sparkfun.com/sparkfun-i2s-audio-breakout-max98357a.html) — $7.50
- [Raspberry Pi Pico 2, our new $5 microcontroller board](https://www.raspberrypi.com/news/raspberry-pi-pico-2-our-new-5-microcontroller-board-on-sale-now/) — Raspberry Pi

Marketplace figures for the INMP441, OLED, speaker, buttons, and breadboard are typical observed
ranges across general electronics retailers rather than quotes from a single vendor, because those
parts have no list price and are sold predominantly in multipacks.
