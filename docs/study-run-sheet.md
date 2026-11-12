# Run sheet: Adaptive vs Fixed

Each participant uses the app twice, with gaze pointing: once Adaptive, once Fixed. Odd numbered
participants do Adaptive first, even numbered do Fixed first. About 40 minutes each.

## Before the first participant

```bash
cp docs/study_forms_template.csv data/study_forms.csv
```

## Each participant

1. Consent. Mount the phone below the screen, 40 to 60 cm from the face. Start GazeStreamer.
2. **Session 1**

   ```bash
   .venv/bin/python tests/study.py P03 1
   ```

   The terminal says which condition this is. Onboarding, signal check, calibration.
3. **Practice, 5 minutes.** Free messaging in any chat. Same length in both sessions: in Adaptive
   this is where the dwell starts learning.
4. **Tasks 1 to 4**, timed on Form C. If stuck for 30 seconds, give one hint.
   1. Open the chat with Priya, go to Settings and change the preferred signal, go back to the chats.
   2. In Priya's chat, type "see you at five" and send it.
   3. Call Priya. When the call connects, end it.
   4. Delete your message "Yes, all good here."
5. **SUS** (Form A). Then a short break.
6. **Session 2**: the same steps with `tests/study.py P03 2`. It reuses the onboarding answers and
   signal levels, so only calibration is repeated.
7. Type both SUS forms and the task times into `data/study_forms.csv`, one row per session:
   `P03,adaptive,...` and `P03,fixed,...`.

Do not restart the app during a session. If it has to be restarted, note it: the analysis uses the
part of the session with the most looks.

## Results

```bash
.venv/bin/python tests/compare.py
```

Saves `result/study/`: `compare.md` (medians and a paired Wilcoxon test per measure),
`compare.png` (each participant's two sessions joined by a line) and `measures.csv`.
