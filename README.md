# Communic-Aid

A gaze and multimodal chat interface for people with motor impairments. People look at buttons
to pick them. Risky actions ask for a second signal (blink and hold, raised eyebrows, saying
"go", or a switch). Two learners adapt the dwell time and the signal to each person.

## How it fits together

![System architecture](figures/architecture.svg)

*The iPhone only senses, the Python core makes every decision, and the browser view only draws.
The dashed arrow is the learning loop: Interaction reports what happened, Outcomes labels it,
and Policy learns from it.*

More detail:

- [docs/how-it-senses.html](docs/how-it-senses.html): the phone, mapping gaze to the screen, and the four signals.
- [docs/how-it-learns.html](docs/how-it-learns.html): the dwell learner and the signal chooser.
- [docs/evaluation-plan.docx](docs/evaluation-plan.docx): the user study, with the SUS and NASA-TLX forms.
- [DESIGN_PLAN.md](DESIGN_PLAN.md): the full design.

## Setup

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
hold, hold **E** to raise eyebrows, press **Y** to say "go", and **S** or Space for the switch.
Esc goes home.

## Run with the iPhone

1. Install the GazeStreamer app from `ARKitGaze/ios` on an iPhone with Face ID (see
   [ARKitGaze/README.md](ARKitGaze/README.md)). The first time, trust your developer profile on
   the phone in Settings, General, VPN & Device Management.
2. Start the core:

   ```bash
   .venv/bin/python -m communicaid --person P01
   ```

3. It prints the Mac's address. Enter it in the phone app (port 5005), turn on
   "Listen for "go"", and press Start. The phone and the Mac must be on the same Wi-Fi.
4. Open http://localhost:8080 in full screen and click to start. Calibration runs first, then the
   signal check.

Fix the phone firmly below the screen, front camera facing the person, 40 to 60 cm away.

If the screen says the phone has stopped sending, check the address in the phone app: the Mac's
address can change when it rejoins Wi-Fi. When the core restarts, the page waits for a new click
before anything starts.

## Running the study

Each participant uses three pointing modes. Give each mode its own ID, so each one starts with a
fresh learner and its own calibration:

| Mode | How | Command |
|---|---|---|
| Gaze only | Head kept still with a chin rest | `.venv/bin/python -m communicaid --person P01-gaze` |
| Head only | The cursor follows where the nose points | `.venv/bin/python -m communicaid --person P01-head --pointing head` |
| Gaze, head free | The everyday system | `.venv/bin/python -m communicaid --person P01-free` |

Rotate the order of the modes between participants. To skip the questions and the signal check in
the second and third mode, copy `signals.json` and `settings.json` from the first mode's folder
into the next mode's folder before starting it. Calibration still runs, as each mode needs its own.
The tasks and forms are in [docs/evaluation-plan.docx](docs/evaluation-plan.docx).

### Typing speed test

A separate test measures typing speed. It shows a short passage, and the person types it by gaze
exactly like composing a message but with no word suggestions. A two minute timer starts on the
first character. When it runs out, typing stops and the screen shows the words per minute. It skips
the onboarding questions and the signal check, and uses the mode's saved calibration.

There are six passages of the same length, and every run shows one the participant has not seen.
In the study each participant types three times on each keyboard, once per mode, which uses all six:

```bash
.venv/bin/python -m communicaid --person P01-gaze --typing grouped
.venv/bin/python -m communicaid --person P01-gaze --typing qwerty
```

Then the same two in `P01-head` (with `--pointing head`) and `P01-free`. Without `--passage`, the
app picks the first passage this participant (`P01`, across all their folders) has not typed yet.
`--passage 1` to `--passage 6` picks one by hand, with a warning if they have seen it before.
The typing test always uses the Fixed condition: the dwell stays at 1000 ms and the learner does
not change it, so every run is timed with the same dwell.

Each run prints its result in the terminal and logs a `typing_result` event with:

- **words per minute:** (characters typed - 1) / 120 seconds × 60 / 5
- **accuracy:** how much of what was typed matches the same stretch of the passage
- **picks per character:** every selection (letters, groups, Back, Space, Backspace) per character typed

`tests/report.py --person P01` averages each keyboard's three runs in `result/P01/typing.md`, adds
each mode's runs to the summary, and lists every run in `typing.csv`. The passages are in
[communicaid/prose.txt](communicaid/prose.txt).

### Options

| Option | Meaning |
|---|---|
| `--pointing head` | Head only: the cursor follows the nose, not the eyes. Needs its own calibration. Default `gaze`. |
| `--typing grouped` or `--typing qwerty` | The typing speed test with that keyboard, instead of the chat app |
| `--passage 1` to `6` | Typing test passage. Default: the first one this participant has not typed yet |
| `--condition fixed` | Fixed baseline: 1000 ms dwell, tier 2 dwell only, tier 3 the preferred signal. Default `adaptive`. |
| `--source mouse` | Mouse test mode, no phone |
| `--raw` | Also log every raw phone frame |
| `--seed 1` | Repeatable learner draws |
| `--quiet` | No learning log in the terminal |
| `--port`, `--udp-port`, `--config` | Other web port, phone port or settings file |

In the browser, **`** opens the study panel (accident costs, reset learning) and **\\** opens the
debug overlay (current group, dwell, last signal choice). Every number, including the accident
costs, is in [config.toml](config.toml).

### What gets saved

Everything for a person goes to `data/<person>/`:

| File | What it holds |
|---|---|
| `events.jsonl` | One line per event: looks, selections, outcomes, learning, signals, calibration, and the buttons on each screen (`layout`) |
| `gaze.jsonl` | The gaze point 30 times a second, with the screen name (for heatmaps), the eye position in mm (`eye_mm`, the head moving) and the head angles in degrees (`head_deg`, left/right and up/down, the head turning) |
| `frames.jsonl` | Every raw phone frame, only with `--raw`. `t` is the Mac clock, `phone_t` the phone's |
| `learner.json`, `calibration.json`, `signals.json`, `settings.json` | What was learned and set up, reused next time |

No message text, video or audio is ever saved. Speech is recognised on the phone, and only the
fact that "go" was heard is sent.

### Results

For a whole participant:

```bash
.venv/bin/python tests/report.py --person P01
```

It finds `data/P01-gaze`, `data/P01-head`, `data/P01-free` and so on, uses the main session of
each, and saves into `result/P01/`:

- `<mode>/heatmap_<screen>.png`: where the person looked on each screen, over the real buttons.
- `<mode>/dwell.png`: how the learner changed the dwell, selection by selection, over every
  session in that folder (learning carries over). One panel per group, one line per tier.
- `summary.md` and `summary.csv`: one column per mode, with selections, accidents, undos,
  give-ups, wrong signals, the final dwell for each group, how much the head moved and turned, and how often each
  signal was asked for and confirmed.

Task times, SUS, NASA-TLX and the ratings are collected on paper. Single plots for one folder:
`tests/plot_heatmap.py --person P01-gaze` and `tests/plot_dwell.py --person P01-gaze`.

### Adaptive vs Fixed study

Each participant does one Adaptive and one Fixed session with gaze pointing, in an order set by
their number. `tests/study.py P03 1` and `tests/study.py P03 2` start the sessions, and
`tests/compare.py` compares the conditions across participants, with SUS and task times from
`data/study_forms.csv`. Steps are in [docs/study-run-sheet.md](docs/study-run-sheet.md).

## Learning log

At start the terminal prints every setting from `config.toml` as a table per section, with the
notes from the file and units filled in. The accident costs and reward values are marked "tuned often".

Then it shows what the learners are doing as it happens, one line per event:

```
00:19  CHOOSE   call             tier 3  tired+steady   -> say "go"   scores: say "go" +0.44   raise eyebrows -0.38   switch -0.82
00:24  OUTCOME  call             tier 3  worked              reward +0.53   check: say "go"
00:24  ROUTER   tier 3  tired+steady   say "go": worked 1, gave up 0, blocked an accident 0, accident 0
00:34  OUTCOME  back             tier 0  worked              reward +0.10   dwell 1500 ms
00:34  DWELL    tired+steady: warm-up 2 of 20 selections, staying at 1500 ms
```

Stray glances are counted and shown as one dim line. In a terminal the outcomes are coloured
(green worked, yellow gave up, cyan blocked an accident, red accident). Add `--quiet` to turn it off.

## Tests

```bash
.venv/bin/python -m pytest
.venv/bin/python tests/simulate.py
```
