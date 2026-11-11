# GazeStreamer (iPhone app)

Streams the face from the iPhone's TrueDepth camera to the Communic-aid core over UDP, about
60 times a second. The phone only senses; the core on the computer makes every decision.

Each frame carries, in ARKit camera space:

- `dir`: the gaze ray, and `eye`: the point between the eyes (metres)
- `head`: where the nose points, used for head pointing
- `blinkL`, `blinkR`, `browIn`, `browOutL`, `browOutR`: blendshapes for the signals
- `dist`: phone to eyes (metres), and `tracked`

When "Listen for "go"" is on, the phone also hears the spoken word on device and sends a
`yes` message.

## Layout

    ios/project.yml               XcodeGen spec
    ios/GazeStreamer/             Swift sources (ARKit + SwiftUI)

Regenerate the Xcode project after editing `project.yml`:

    cd ios && xcodegen generate

## Setup

These are one-time steps that need your hands (password, Apple ID, the phone).

**1. Point the toolchain at Xcode**, if it is on Command Line Tools:

    sudo xcode-select -s /Applications/Xcode.app/Contents/Developer

**2. Install the iOS platform**, if builds fail with "iOS ... is not installed":

    xcodebuild -downloadPlatform iOS

**3. Turn on Developer Mode on the iPhone.** Settings > Privacy & Security > Developer Mode > On,
then restart the phone.

**4. Sign and run.**

    open ios/GazeStreamer.xcodeproj

In Signing & Capabilities pick your Apple ID under Team. A free account works, but the
certificate expires after 7 days and you rebuild to renew it. Change the bundle identifier if
`com.sinngam.gazestreamer` is taken. Pick the iPhone as the run destination and press Run. On the
first launch, approve the certificate in Settings > General > VPN & Device Management.

Then follow "Run with the iPhone" in the main [README](../README.md).

## Notes

Gaze is in **camera space**, so the phone, not the room, is the frame of reference. ARKit's
camera looks down -z, so a face in front sits at negative z. Keep the phone still after
calibrating: the calibration learns a fixed phone to screen geometry.

ARKit gaze is accurate to about 1 to 2 degrees, which is tens of pixels on screen. That is why
the buttons are large. The mapping is not the limit, the sensor is.
