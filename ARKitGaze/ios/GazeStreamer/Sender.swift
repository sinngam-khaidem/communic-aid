import Foundation
import Network

/// One reading from the face, in the contract format (DESIGN_PLAN 3.1).
struct FrameMessage: Encodable {
    var type = "frame"
    let seq: UInt32
    let t: TimeInterval
    let dir: [Float]?          // gaze ray in camera space; nil when the face is lost
    let eye: [Float]?          // midpoint between the eyes in camera space, metres; nil when lost
    let head: [Float]?         // where the nose points, in camera space, length 1; nil when lost
    let blinkL: Float
    let blinkR: Float
    let browIn: Float
    let browOutL: Float
    let browOutR: Float
    let tracked: Bool
    let dist: Float            // phone to eyes, metres
}

private struct YesMessage: Encodable {
    var type = "yes"
    let t: TimeInterval
}

private struct PreviewMessage: Encodable {
    var type = "preview"
    let t: TimeInterval
    let jpg: String           // base64 JPEG, about 120 x 160
}

/// Sends messages to the Mac over UDP. Knows nothing about ARKit or speech.
final class Sender {
    private var connection: NWConnection?
    private let queue = DispatchQueue(label: "gaze.udp")
    private let encoder = JSONEncoder()
    var onError: ((String) -> Void)?

    func open(host: String, port: UInt16) -> Bool {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else { return false }
        connection?.cancel()
        let conn = NWConnection(host: NWEndpoint.Host(host), port: nwPort, using: .udp)
        conn.stateUpdateHandler = { [weak self] state in
            guard case .failed(let error) = state else { return }
            DispatchQueue.main.async { self?.onError?("UDP failed: \(error.localizedDescription)") }
        }
        conn.start(queue: queue)
        connection = conn
        return true
    }

    func close() {
        connection?.cancel()
        connection = nil
    }

    func send(_ frame: FrameMessage) {
        transmit(frame)
    }

    func sendYes() {
        transmit(YesMessage(t: ProcessInfo.processInfo.systemUptime))
    }

    func sendPreview(_ jpeg: Data) {
        transmit(PreviewMessage(t: ProcessInfo.processInfo.systemUptime, jpg: jpeg.base64EncodedString()))
    }

    private func transmit<T: Encodable>(_ message: T) {
        guard let connection, let data = try? encoder.encode(message) else { return }
        connection.send(content: data, completion: .idempotent)
    }
}
