# Communic-aid

A gaze and multimodal chat prototype for people with motor impairments. People look at buttons
to pick them. Risky actions ask for a second signal (blink and hold, raised eyebrows, saying
"yes", or a switch). Two learners adapt the dwell time and the signal to each person.

The design is in [DESIGN_PLAN.md](DESIGN_PLAN.md).

## Setup (once)

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

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
