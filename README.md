# Communic-aid

A gaze and multimodal chat prototype for people with motor impairments. People look at buttons
to pick them. Risky actions ask for a second signal (blink and hold, raised eyebrows, saying
"yes", or a switch). Two learners adapt the dwell time and the signal to each person.

The design is in [DESIGN_PLAN.md](DESIGN_PLAN.md).

## How it fits together

![System architecture](figures/architecture.svg)

*The iPhone only senses, the Python core makes every decision, and the browser view only draws.
The dashed arrow is the learning loop: Interaction reports what happened, Outcomes labels it,
and Policy learns from it.*

## Setup (once)

```bash
./setup.sh
```

It creates `.venv` (with [uv](https://docs.astral.sh/uv/) if you have it, otherwise Python 3.11
or newer) and installs the app. Add `--test` to run the tests afterwards. Running it again is safe.

## Run without the phone (mouse test mode)

```bash
.venv/bin/python -m communicaid --person P01 --source mouse
```

Open http://localhost:8080 and click to start. The mouse is your gaze. Hold **B** to blink and
hold, hold **E** to raise eyebrows, press **Y** to say "yes", and **S** or Space for the switch.
Esc goes home.

## Run with the iPhone

1. Build and install `ARKitGaze/ios` on an iPhone with Face ID (see `ARKitGaze/README.md`).
2. Start the core:

   ```bash
   .venv/bin/python -m communicaid --person P01
   ```

3. It prints the Mac's address. Enter it in the phone app and press Start.
4. Open http://localhost:8080 in full screen and click to start. Calibration runs first.

Fix the phone below the screen, front camera facing the person, 40 to 60 cm away.

## Learning log

The terminal shows what the learners are doing as it happens, one line per event:

```
00:19  CHOOSE   call             tier 3  tired+steady   -> say "yes"   scores: say "yes" +0.44   raise eyebrows -0.38   switch -0.82
00:24  OUTCOME  call             tier 3  worked              reward +0.53   check: say "yes"
00:24  ROUTER   tier 3  tired+steady   say "yes": worked 1, gave up 0, blocked an accident 0, accident 0
00:34  OUTCOME  back             tier 0  worked              reward +0.10   dwell 1500 ms
00:34  DWELL    tired+steady: warm-up 2 of 20 selections, staying at 1500 ms
```

Stray glances are counted and shown as one dim line. In a terminal the outcomes are coloured
(green worked, yellow gave up, cyan blocked an accident, red accident). Add `--quiet` to turn it off.

## Study options

| Option | Meaning |
|---|---|
| `--condition fixed` | Fixed baseline: 1000 ms dwell, tier 2 dwell only, tier 3 the preferred signal |
| `--raw` | Also log every raw frame |
| `--seed 1` | Repeatable learner draws |

In the browser, **`** opens the study panel (accident costs, reset learning) and **\\** opens the
debug overlay (current group, dwell, last router choice).

Every number, including the accident costs, is in [config.toml](config.toml). Logs and saved
learning go to `data/<person>/`.

## Tests

```bash
.venv/bin/python -m pytest
.venv/bin/python tests/simulate.py
```
