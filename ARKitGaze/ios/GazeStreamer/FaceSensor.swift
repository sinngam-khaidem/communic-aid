import ARKit
import Combine
import simd

/// Runs ARKit face tracking on the TrueDepth camera and turns each frame into a FrameMessage.
///
/// Senses only: no network and no decisions. Everything is reported in ARKit **camera space**
/// (the phone's own frame: +x right, +y up, -z out of the front camera). The phone is fixed
/// below the screen, so the camera frame is a stable reference for the screen.
final class FaceSensor: NSObject, ObservableObject, ARSessionDelegate {

    @Published private(set) var isSupported = ARFaceTrackingConfiguration.isSupported
    @Published private(set) var isRunning = false
    @Published private(set) var faceVisible = false
    @Published private(set) var framesSent = 0
    @Published private(set) var status = "Idle"
    @Published private(set) var yawDegrees: Float = 0
    @Published private(set) var pitchDegrees: Float = 0
    @Published private(set) var browLevel: Float = 0

    /// Called for every camera frame, face or no face, so the Mac notices tracking loss.
    var onFrame: ((FrameMessage) -> Void)?
    /// Microphone audio captured by ARKit itself, for speech.
    var onAudio: ((CMSampleBuffer) -> Void)?
    /// A tiny JPEG of the camera image with landmarks, about 10 a second, for the Mac's corner window.
    var onPreview: ((Data) -> Void)?
    var previewEnabled = true

    let session = ARSession()
    private var sequence: UInt32 = 0
    private let preview = FacePreview()
    private var lastPreview: TimeInterval = 0

    override init() {
        super.init()
        session.delegate = self
    }

    func start(withAudio: Bool) {
        guard isSupported else {
            status = "This device has no TrueDepth face tracking."
            return
        }
        let config = ARFaceTrackingConfiguration()
        config.maximumNumberOfTrackedFaces = 1
        config.isLightEstimationEnabled = false
        config.providesAudioData = withAudio
        session.run(config, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
        framesSent = 0
        status = "Running"
    }

    func stop() {
        session.pause()
        isRunning = false
        faceVisible = false
        status = "Stopped"
    }

    // MARK: - ARSessionDelegate

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard isRunning else { return }
        sequence &+= 1

        guard let face = frame.anchors.compactMap({ $0 as? ARFaceAnchor }).first, face.isTracked else {
            onFrame?(FrameMessage(seq: sequence, t: frame.timestamp, dir: nil, eye: nil, blinkL: 0, blinkR: 0,
                                  browIn: 0, browOutL: 0, browOutR: 0, tracked: false, dist: 0))
            sendPreview(frame, face: nil)
            if faceVisible { DispatchQueue.main.async { self.faceVisible = false } }
            return
        }

        // Eye midpoint and the point being looked at, both in world space.
        let faceToWorld = face.transform
        let leftEyeWorld = faceToWorld * face.leftEyeTransform
        let rightEyeWorld = faceToWorld * face.rightEyeTransform
        let eyeMidWorld = (leftEyeWorld.translation + rightEyeWorld.translation) * 0.5
        let lookAtWorld = (faceToWorld * SIMD4<Float>(face.lookAtPoint, 1)).xyz

        // Re-express in camera space so the phone, not the session origin, is the reference.
        let view = frame.camera.viewMatrix(for: .portrait)
        let eyeMid = (view * SIMD4<Float>(eyeMidWorld, 1)).xyz
        let lookAt = (view * SIMD4<Float>(lookAtWorld, 1)).xyz
        let direction = simd_normalize(lookAt - eyeMid)

        let shapes = face.blendShapes
        let value = { (key: ARFaceAnchor.BlendShapeLocation) in shapes[key]?.floatValue ?? 0 }
        let message = FrameMessage(
            seq: sequence,
            t: frame.timestamp,
            dir: [direction.x, direction.y, direction.z],
            eye: [eyeMid.x, eyeMid.y, eyeMid.z],
            blinkL: value(.eyeBlinkLeft),
            blinkR: value(.eyeBlinkRight),
            browIn: value(.browInnerUp),
            browOutL: value(.browOuterUpLeft),
            browOutR: value(.browOuterUpRight),
            tracked: true,
            dist: simd_length(eyeMid)
        )
        onFrame?(message)
        sendPreview(frame, face: face)

        // Cheap readout for the on-device UI; the Mac does the real mapping.
        let yaw = atan2(direction.x, direction.z) * 180 / .pi
        let pitch = atan2(direction.y, direction.z) * 180 / .pi
        let brow = (message.browIn + message.browOutL + message.browOutR) / 3
        let count = Int(sequence)
        DispatchQueue.main.async {
            self.faceVisible = true
            self.yawDegrees = yaw
            self.pitchDegrees = pitch
            self.browLevel = brow
            self.framesSent = count
        }
    }

    private func sendPreview(_ frame: ARFrame, face: ARFaceAnchor?) {
        guard previewEnabled, let onPreview, frame.timestamp - lastPreview >= 0.1 else { return }
        lastPreview = frame.timestamp
        if let jpeg = preview.jpeg(frame: frame, face: face) { onPreview(jpeg) }
    }

    func session(_ session: ARSession, didOutputAudioSampleBuffer audioSampleBuffer: CMSampleBuffer) {
        onAudio?(audioSampleBuffer)
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        DispatchQueue.main.async {
            self.status = "AR error: \(error.localizedDescription)"
            self.isRunning = false
        }
    }
}

private extension simd_float4x4 {
    var translation: SIMD3<Float> { SIMD3(columns.3.x, columns.3.y, columns.3.z) }
}

private extension SIMD4 where Scalar == Float {
    var xyz: SIMD3<Float> { SIMD3(x, y, z) }
}
