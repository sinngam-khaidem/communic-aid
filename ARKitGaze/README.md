# ARKit TrueDepth gaze -> macOS cursor

Streams gaze from the iPhone's TrueDepth camera to this Mac over UDP, maps it to
screen coordinates with a nine-point calibration, and drives the cursor.

Unlike the webcam trackers in this repo, gaze here comes from `ARFaceAnchor`,
which uses the depth sensor rather than fitting an ellipse to an iris in RGB.

```
iPhone (TrueDepth, 60 Hz)          Mac
  ARFaceTrackingConfiguration
  -> lookAtPoint + eye transforms
  -> gaze ray in camera space  --UDP-->  gaze_receiver.py
                                          -> yaw / pitch
                                          -> 9-point quadratic fit
                                          -> EMA smoothing
                                          -> pyautogui cursor
```

## Layout

    setup.sh                      creates .venv with uv
    run.sh                        launches the receiver
    ios/project.yml               XcodeGen spec
    ios/GazeStreamer/             Swift sources (ARKit + SwiftUI)
    mac/gaze_receiver.py          receiver, calibration UI, cursor control

Regenerate the Xcode project after editing `project.yml`:

    cd ios && xcodegen generate

## Setup

Steps 1, 2 and 3 are one-time and need your hands (password, Apple ID, device UI).

**1. Point the toolchain at Xcode.** It is currently on Command Line Tools, so
`xcodebuild` cannot see any iOS platform:

    sudo xcode-select -s /Applications/Xcode.app/Contents/Developer

**2. Install the iOS platform.** Xcode 26 ships the SDK headers but not the
platform, which is why builds fail with "iOS 26.1 is not installed". Several GB:

    xcodebuild -downloadPlatform iOS

**3. Enable Developer Mode on the iPhone.** Settings > Privacy & Security >
Developer Mode > On, then reboot the phone.

**4. Sign and run.**

    open ios/GazeStreamer.xcodeproj

In Signing & Capabilities pick your Apple ID under Team. A free account works;
the certificate expires after 7 days and you rebuild to renew. Change the bundle
identifier if `com.sinngam.gazestreamer` is taken. Select the iPhone as the run
destination and press Run. On first launch the phone will refuse to open it
until you approve the certificate in Settings > General > VPN & Device
Management.

**5. Grant Accessibility to your terminal.** Without it `pyautogui.moveTo`
silently does nothing, which is the current state on this machine. System
Settings > Privacy & Security > Accessibility, add the terminal app, restart it.

## Running

    ./setup.sh    # once, creates .venv via uv
    ./run.sh

It prints the address to enter in the phone app. Clamp the phone beside the
monitor with the front camera facing you and keep it still: the calibration
learns a fixed phone-to-screen geometry, so moving the phone invalidates it.

Press Start on the phone, then Calibrate on the Mac and follow the nine dots.
The fit error is reported in pixels; under about 30 px is a good calibration.
Calibration is saved to `mac/calibration.json` and reloaded on next launch.

Then toggle Mouse control on. The smoothing slider trades lag against jitter.

## Accuracy

Measured against a simulated screen with the real calibration and mapping code,
varying only the gaze noise from the phone:

| ARKit gaze noise | mean error | p90 error |
|---|---|---|
| 0.25 deg | 6 px  | 9 px  |
| 0.5 deg  | 10 px | 17 px |
| 1.0 deg  | 18 px | 34 px |
| 1.5 deg  | 27 px | 51 px |
| 2.0 deg  | 36 px | 68 px |

ARKit gaze in practice sits nearer the 1 to 2 degree end, so expect tens of
pixels: comfortable for large targets, not for hitting a close button. The
mapping itself is not the limit, the sensor is.

## Notes

The phone reports gaze in ARKit **camera space**, not world space, so the phone
rather than the session origin is the reference frame. ARKit's camera looks down
-z, so a face in front sits at negative z and gaze back toward the screen has
positive dz; yaw and pitch therefore use `atan2(x, z)` and `atan2(y, z)`. Using
`-z` puts the angles at the 180 degree wrap, where the sign flips erratically.

The quadratic basis `[1, y, p, y*p, y^2, p^2]` absorbs axis flips and mirroring,
so if the cursor moves the wrong way the fix is to recalibrate, not to edit signs.

Blink blendshapes (`blinkL`, `blinkR`) are streamed and displayed but not wired
to clicking. They are the obvious hook for dwell or blink selection.
