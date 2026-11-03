#!/usr/bin/env python3
"""
Receive ARKit TrueDepth gaze from the iPhone app and drive the macOS cursor.

The phone streams a gaze ray in its own camera frame. This script learns the
mapping from that ray to screen pixels with a nine-point calibration, then
smooths the result and moves the cursor.

"""

import json
import socket
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path

import numpy as np
import pyautogui

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = False  # gaze wanders into corners constantly

HOST, PORT = "0.0.0.0", 5005
CALIBRATION_FILE = Path(__file__).with_name("calibration.json")

# Nine targets as fractions of the screen.
TARGET_FRACTIONS = [(fx, fy) for fy in (0.1, 0.5, 0.9) for fx in (0.1, 0.5, 0.9)]
SETTLE_SECONDS = 1.2      # let the eyes land on the dot
COLLECT_SECONDS = 0.8     # then average over this window
STALE_AFTER = 0.5         # seconds without a packet before we stop moving
GRAB_PIXELS = 25          # physical mouse movement this large takes control back
OFF_SCREEN_MARGIN = 400   # predictions further outside the screen are ignored


def features(yaw, pitch):
    """Quadratic basis. Absorbs axis flips and mild lens/geometry distortion."""
    yaw = np.asarray(yaw, dtype=float)
    pitch = np.asarray(pitch, dtype=float)
    return np.stack([np.ones_like(yaw), yaw, pitch, yaw * pitch, yaw**2, pitch**2], axis=-1)


class GazeReceiver(threading.Thread):
    """Listens for UDP packets and keeps the most recent sample."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, PORT))
        self.sock.settimeout(0.5)
        self.lock = threading.Lock()
        self.latest = None          # (yaw_deg, pitch_deg, blinkL, blinkR)
        self.last_time = 0.0
        self.count = 0
        self.running = True

    def run(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                s = json.loads(data)
                dx, dy, dz = s["dir"]
            except (ValueError, KeyError):
                continue
            yaw = np.degrees(np.arctan2(dx, dz))
            pitch = np.degrees(np.arctan2(dy, dz))
            with self.lock:
                self.latest = (yaw, pitch, s.get("blinkL", 0.0), s.get("blinkR", 0.0))
                self.last_time = time.time()
                self.count += 1

    def sample(self):
        with self.lock:
            return self.latest, self.last_time, self.count

    def stop(self):
        self.running = False
        self.sock.close()


class GazeApp:
    def __init__(self):
        self.rx = GazeReceiver()
        self.rx.start()

        self.coef_x = None
        self.coef_y = None
        self.mu = None            # mean of calibration yaw/pitch
        self.sigma = None         # spread of calibration yaw/pitch
        self.observations = None  # raw calibration readings, kept for diagnosis
        self.residual = None
        self.mouse_enabled = False
        self.last_commanded = None   # where we last put the pointer
        self.alpha = 0.35
        self.smoothed = None
        self.last_count = 0
        self.last_rate_time = time.time()
        self.rate = 0.0

        self.root = tk.Tk()
        self.root.title("ARKit Gaze")
        self.root.attributes("-topmost", True)
        self.root.geometry("340x250")
        self._build_panel()
        self._load_calibration()
        self.root.after(16, self._tick)

    # ---------------------------------------------------------------- panel

    def _build_panel(self):
        pad = {"padx": 12, "pady": 4}
        self.status = tk.Label(self.root, text="waiting for phone", font=("Menlo", 12), justify="left")
        self.status.pack(anchor="w", **pad)

        self.readout = tk.Label(self.root, text="", font=("Menlo", 11), fg="#555", justify="left")
        self.readout.pack(anchor="w", **pad)

        self.calib_label = tk.Label(self.root, text="not calibrated", font=("Menlo", 11), fg="#555")
        self.calib_label.pack(anchor="w", **pad)

        tk.Button(self.root, text="Calibrate (9 points)", command=self.calibrate).pack(fill="x", **pad)

        self.mouse_button = tk.Button(self.root, text="Mouse control: OFF", command=self.toggle_mouse)
        self.mouse_button.pack(fill="x", **pad)

        tk.Scale(self.root, from_=0.05, to=1.0, resolution=0.05, orient="horizontal",
                 label="smoothing (higher = snappier)", command=self._set_alpha).pack(fill="x", **pad)

        tk.Button(self.root, text="Quit", command=self.quit).pack(fill="x", **pad)

    def _set_alpha(self, value):
        self.alpha = float(value)

    def toggle_mouse(self):
        if self.coef_x is None:
            self.status.config(text="calibrate first")
            return
        self.mouse_enabled = not self.mouse_enabled
        self.last_commanded = None
        self.mouse_button.config(text=f"Mouse control: {'ON' if self.mouse_enabled else 'OFF'}")

    # ---------------------------------------------------------- calibration

    def calibrate(self):
        sample, _, _ = self.rx.sample()
        if sample is None:
            self.status.config(text="no gaze data yet")
            return

        overlay = tk.Toplevel(self.root)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        canvas = tk.Canvas(overlay, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        overlay.update()

        w, h = overlay.winfo_width(), overlay.winfo_height()
        observations, targets = [], []

        def show(index):
            if index >= len(TARGET_FRACTIONS):
                overlay.destroy()
                self._fit(observations, targets)
                return

            fx, fy = TARGET_FRACTIONS[index]
            cx, cy = fx * w, fy * h
            canvas.delete("all")
            canvas.create_text(w / 2, 40, fill="#666", font=("Helvetica", 16),
                               text=f"Look at the dot  ({index + 1}/{len(TARGET_FRACTIONS)})")
            canvas.create_oval(cx - 16, cy - 16, cx + 16, cy + 16, fill="#e0453a", outline="")
            canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="white", outline="")

            buf = deque()

            def collect(deadline):
                s, t, _ = self.rx.sample()
                if s is not None and time.time() - t < STALE_AFTER:
                    buf.append((s[0], s[1]))
                if time.time() < deadline:
                    overlay.after(16, lambda: collect(deadline))
                elif buf:
                    arr = np.array(buf)
                    observations.append(np.median(arr, axis=0))
                    targets.append((cx, cy))
                    show(index + 1)
                else:
                    overlay.destroy()
                    self.status.config(text="lost the phone stream during calibration")

            overlay.after(int(SETTLE_SECONDS * 1000),
                          lambda: collect(time.time() + COLLECT_SECONDS))

        show(0)

    def _fit(self, observations, targets):
        """Least squares with the angles standardised and a ridge term.

        Fitting raw degrees is badly conditioned: nine points span only a few
        degrees, so the quadratic terms take on huge coefficients that fit the
        dots and then explode a short distance outside them. Standardising the
        inputs and nudging the solution toward zero keeps the surface sane.
        """
        obs = np.array(observations)
        tgt = np.array(targets)

        self.mu = obs.mean(axis=0)
        self.sigma = obs.std(axis=0)
        self.sigma[self.sigma < 1e-6] = 1.0

        z = (obs - self.mu) / self.sigma
        A = features(z[:, 0], z[:, 1])
        gram = A.T @ A + 1e-2 * np.eye(A.shape[1])
        self.coef_x = np.linalg.solve(gram, A.T @ tgt[:, 0])
        self.coef_y = np.linalg.solve(gram, A.T @ tgt[:, 1])

        pred = np.stack([A @ self.coef_x, A @ self.coef_y], axis=-1)
        self.residual = float(np.sqrt(((pred - tgt) ** 2).sum(axis=1).mean()))
        self.observations = obs

        # A healthy calibration sweeps several degrees in each axis. If the dots
        # barely moved the eye, the fit has nothing to anchor on and will throw
        # the cursor far off screen the moment you look anywhere new.
        span = obs.max(axis=0) - obs.min(axis=0)
        warn = "  SPAN TOO SMALL, recalibrate" if min(span) < 2.0 else ""
        self.calib_label.config(
            text=f"fit error {self.residual:.0f} px | span {span[0]:.1f} x {span[1]:.1f} deg{warn}")
        print(f"calibration observations (yaw, pitch):\n{np.round(obs, 2)}")
        print(f"span {span[0]:.2f} x {span[1]:.2f} deg, residual {self.residual:.1f} px", flush=True)
        self._save_calibration()

    def _predict(self, yaw, pitch):
        z = (np.array([yaw, pitch]) - self.mu) / self.sigma
        f = features(z[0], z[1])
        return float(f @ self.coef_x), float(f @ self.coef_y)

    def _save_calibration(self):
        CALIBRATION_FILE.write_text(json.dumps({
            "version": 2,
            "coef_x": self.coef_x.tolist(),
            "coef_y": self.coef_y.tolist(),
            "mu": self.mu.tolist(),
            "sigma": self.sigma.tolist(),
            "residual": self.residual,
            "observations": self.observations.tolist(),
        }, indent=2))

    def _load_calibration(self):
        if not CALIBRATION_FILE.exists():
            return
        try:
            d = json.loads(CALIBRATION_FILE.read_text())
            if d.get("version") != 2:
                raise KeyError("old format")
            coef_x = np.array(d["coef_x"])
            coef_y = np.array(d["coef_y"])
            mu = np.array(d["mu"])
            sigma = np.array(d["sigma"])
        except (ValueError, KeyError):
            return
        self.coef_x, self.coef_y, self.mu, self.sigma = coef_x, coef_y, mu, sigma
        self.residual = d.get("residual")
        self.calib_label.config(text=f"loaded calibration, fit error {self.residual:.0f} px")

    # ----------------------------------------------------------- main loop

    def _tick(self):
        sample, last_time, count = self.rx.sample()
        now = time.time()

        if now - self.last_rate_time >= 1.0:
            self.rate = (count - self.last_count) / (now - self.last_rate_time)
            self.last_count, self.last_rate_time = count, now

        fresh = sample is not None and now - last_time < STALE_AFTER
        if not fresh:
            self.status.config(text="waiting for phone", fg="#b00")
            self.readout.config(text="")
        else:
            yaw, pitch, bl, br = sample
            self.status.config(text=f"streaming  {self.rate:.0f} pkt/s", fg="#070")
            self.readout.config(text=f"yaw {yaw:+6.1f}°   pitch {pitch:+6.1f}°\n"
                                     f"blink L {bl:.2f}  R {br:.2f}")

            if self.mouse_enabled:
                self._disarm_if_grabbed()
            if self.mouse_enabled and self.coef_x is not None:
                x, y = self._predict(yaw, pitch)
                if self.smoothed is None:
                    self.smoothed = np.array([x, y])
                else:
                    self.smoothed += self.alpha * (np.array([x, y]) - self.smoothed)
                sw, sh = pyautogui.size()
                sx, sy = self.smoothed
                # A wild prediction means the fit is extrapolating. Pinning the
                # pointer to a corner in that case just takes the mouse hostage.
                if (-OFF_SCREEN_MARGIN < sx < sw + OFF_SCREEN_MARGIN
                        and -OFF_SCREEN_MARGIN < sy < sh + OFF_SCREEN_MARGIN):
                    cx = int(np.clip(sx, 0, sw - 1))
                    cy = int(np.clip(sy, 0, sh - 1))
                    pyautogui.moveTo(cx, cy)
                    self.last_commanded = (cx, cy)
                else:
                    self.status.config(text="gaze off screen, not moving", fg="#b00")

        self.root.after(16, self._tick)

    def _set_mouse(self, on, message=""):
        self.mouse_enabled = on
        self.last_commanded = None
        self.mouse_button.config(text=f"Mouse control: {'ON' if on else 'OFF'}")
        if message:
            self.status.config(text=message, fg="#b00")

    def _disarm_if_grabbed(self):
        """Touching the physical mouse takes control back immediately."""
        if self.last_commanded is None:
            return
        here = pyautogui.position()
        if (abs(here.x - self.last_commanded[0]) > GRAB_PIXELS
                or abs(here.y - self.last_commanded[1]) > GRAB_PIXELS):
            self._set_mouse(False, "you moved the mouse, gaze control off")

    def quit(self):
        self.rx.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    print(f"Listening on {local_ip()}:{PORT}")
    print("Enter that address in the iPhone app, press Start, then Calibrate here.")
    GazeApp().run()
