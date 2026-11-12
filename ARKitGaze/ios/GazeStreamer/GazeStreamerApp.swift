import SwiftUI

@main
struct GazeStreamerApp: App {
    @StateObject private var streamer = Streamer()

    var body: some Scene {
        WindowGroup {
            ContentView(streamer: streamer, sensor: streamer.sensor)
                .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        }
    }
}

/// Connects the three parts: FaceSensor and SpeechListener sense, Sender sends to the Mac.
final class Streamer: ObservableObject {
    let sensor = FaceSensor()
    let speech = SpeechListener()
    let sender = Sender()
    @Published var speechStatus = "Speech off"
    @Published var error: String?

    init() {
        sensor.onFrame = { [sender] frame in sender.send(frame) }
        sensor.onAudio = { [speech] buffer in speech.append(buffer) }
        sensor.onPreview = { [sender] jpeg in sender.sendPreview(jpeg) }
        speech.onYes = { [sender] in sender.sendYes() }
        speech.onStatus = { [weak self] text in DispatchQueue.main.async { self?.speechStatus = text } }
        speech.onHeard = { [weak self] text in DispatchQueue.main.async { self?.speechStatus = "Heard: \(text)" } }
        sender.onError = { [weak self] text in self?.error = text }
    }

    func start(host: String, port: UInt16, listen: Bool, preview: Bool) {
        error = nil
        sensor.previewEnabled = preview
        guard sender.open(host: host, port: port) else {
            error = "Invalid port."
            return
        }
        if listen {
            SpeechListener.requestPermission { [weak self] granted in
                guard let self else { return }
                self.sensor.start(withAudio: granted)
                if granted { self.speech.start() } else { self.speechStatus = "Speech permission not given" }
            }
        } else {
            sensor.start(withAudio: false)
        }
    }

    func stop() {
        speech.stop()
        sensor.stop()
        sender.close()
    }
}
