import ARKit
import Combine
import Network
import simd

/// Runs an ARKit face-tracking session on the TrueDepth camera and streams the
/// gaze ray to a UDP listener on the desktop.
///
/// Everything is reported in ARKit **camera space** (the phone's own frame:
/// +x right, +y up, -z pointing out of the front camera) rather than world
/// space. The phone is assumed to be clamped in a fixed position next to the
/// monitor, so the camera frame is a stable reference for the screen.
final class GazeTracker: NSObject, ObservableObject, ARSessionDelegate {

    @Published private(set) var isSupported = ARFaceTrackingConfiguration.isSupported
    @Published private(set) var isRunning = false
    @Published private(set) var faceVisible = false
    @Published private(set) var packetsSent = 0
    @Published private(set) var status = "Idle"
    @Published private(set) var yawDegrees: Float = 0
    @Published private(set) var pitchDegrees: Float = 0

    let session = ARSession()

    private var connection: NWConnection?
    private let sendQueue = DispatchQueue(label: "gaze.udp")
    private var sequence: UInt32 = 0

    override init() {
        super.init()
        session.delegate = self
    }

    // MARK: - Session control

    func start(host: String, port: UInt16) {
        guard isSupported else {
            status = "This device has no TrueDepth face tracking."
            return
        }
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            status = "Invalid port."
            return
        }

        openConnection(host: host, port: nwPort)

        let config = ARFaceTrackingConfiguration()
        config.maximumNumberOfTrackedFaces = 1
        config.isLightEstimationEnabled = false
        session.run(config, options: [.resetTracking, .removeExistingAnchors])

        isRunning = true
        packetsSent = 0
        status = "Streaming to \(host):\(port)"
    }

    func stop() {
        session.pause()
        connection?.cancel()
        connection = nil
        isRunning = false
        faceVisible = false
        status = "Stopped"
    }

    private func openConnection(host: String, port: NWEndpoint.Port) {
        connection?.cancel()
        let conn = NWConnection(host: NWEndpoint.Host(host), port: port, using: .udp)
        conn.stateUpdateHandler = { [weak self] state in
            guard case .failed(let error) = state else { return }
            DispatchQueue.main.async { self?.status = "UDP failed: \(error.localizedDescription)" }
        }
        conn.start(queue: sendQueue)
        connection = conn
    }

    // MARK: - ARSessionDelegate

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        guard isRunning else { return }

        guard let face = frame.anchors.compactMap({ $0 as? ARFaceAnchor }).first, face.isTracked else {
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

        // Raw per-eye orientation. Each eye looks along the -Z axis of its own
        // transform. lookAtPoint is a smoothed, conservative derivative of these
        // and compresses real eye rotation to about a tenth of its true swing,
        // so stream both and let the desktop measure which actually moves.
        let leftAxis = simd_normalize(leftEyeWorld.zAxis)
        let rightAxis = simd_normalize(rightEyeWorld.zAxis)
        let eyeAxisWorld = simd_normalize(leftAxis + rightAxis)
        let eyeDirection = simd_normalize((view * SIMD4<Float>(eyeAxisWorld, 0)).xyz)

        let blinkLeft = face.blendShapes[.eyeBlinkLeft]?.floatValue ?? 0
        let blinkRight = face.blendShapes[.eyeBlinkRight]?.floatValue ?? 0

        sequence &+= 1
        let sample = GazeSample(
            seq: sequence,
            t: frame.timestamp,
            eye: [eyeMid.x, eyeMid.y, eyeMid.z],
            dir: [direction.x, direction.y, direction.z],
            dirEye: [eyeDirection.x, eyeDirection.y, eyeDirection.z],
            blinkL: blinkLeft,
            blinkR: blinkRight
        )
        send(sample)

        // Cheap readout for the on-device UI; the desktop does the real mapping.
        let yaw = atan2(direction.x, direction.z) * 180 / .pi
        let pitch = atan2(direction.y, direction.z) * 180 / .pi
        DispatchQueue.main.async {
            self.faceVisible = true
            self.yawDegrees = yaw
            self.pitchDegrees = pitch
            self.packetsSent = Int(self.sequence)
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        DispatchQueue.main.async {
            self.status = "AR error: \(error.localizedDescription)"
            self.isRunning = false
        }
    }

    private func send(_ sample: GazeSample) {
        guard let connection, let data = try? JSONEncoder().encode(sample) else { return }
        connection.send(content: data, completion: .idempotent)
    }
}

private struct GazeSample: Encodable {
    let seq: UInt32
    let t: TimeInterval
    let eye: [Float]
    let dir: [Float]
    let dirEye: [Float]
    let blinkL: Float
    let blinkR: Float
}

private extension simd_float4x4 {
    var translation: SIMD3<Float> { SIMD3(columns.3.x, columns.3.y, columns.3.z) }
    var zAxis: SIMD3<Float> { SIMD3(columns.2.x, columns.2.y, columns.2.z) }
}

private extension SIMD4 where Scalar == Float {
    var xyz: SIMD3<Float> { SIMD3(x, y, z) }
}
