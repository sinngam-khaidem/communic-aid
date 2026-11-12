import AVFoundation
import Foundation
import Speech

/// Listens for the confirmation word "go" with Apple's Speech framework, fully on device.
///
/// Audio comes from ARKit (`providesAudioData`), so nothing else touches the microphone.
/// Audio never leaves the phone: only a "yes" event (the confirmation signal) is reported. If this phone cannot
/// recognise speech on device, the listener stays off rather than sending audio to a server.
final class SpeechListener {
    /// Words that count as the confirmation: "go". It is short and easy to say. The Mac only uses the
    /// signal while a button is waiting for it, so "go" in ordinary talk does nothing.
    var words: Set<String> = ["go"]
    var onYes: (() -> Void)?
    var onStatus: ((String) -> Void)?
    /// The latest words heard, shown on the phone so the researcher can see what it understood.
    var onHeard: ((String) -> Void)?

    private let recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var heard = 0
    private var startedAt = Date()
    private var running = false
    private var buffers = 0
    private var lastReport = Date()
    private var lastHeard = ""

    /// Printed lines show up in the Mac's console when the app is launched from Xcode or devicectl.
    private func log(_ text: String) { print("[speech] \(text)") }

    init() {
        let india = SFSpeechRecognizer(locale: Locale(identifier: "en-IN"))
        if let india, india.supportsOnDeviceRecognition {
            recognizer = india
        } else {
            recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
        }
    }

    var isAvailable: Bool { recognizer?.supportsOnDeviceRecognition ?? false }

    static func requestPermission(_ done: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            DispatchQueue.main.async { done(status == .authorized) }
        }
    }

    func start() {
        log("speech permission \(SFSpeechRecognizer.authorizationStatus().rawValue) (3 = allowed), "
            + "microphone \(AVAudioApplication.shared.recordPermission.rawValue) (1735552628 = allowed), "
            + "language \(recognizer?.locale.identifier ?? "none"), on device \(isAvailable), "
            + "ready \(recognizer?.isAvailable ?? false)")
        guard isAvailable else {
            onStatus?("On-device speech is not available on this phone")
            return
        }
        running = true
        restart()
        onStatus?("Listening for \"go\"")
    }

    func stop() {
        running = false
        task?.cancel()
        request?.endAudio()
        task = nil
        request = nil
        onStatus?("Speech off")
    }

    /// Called with each audio buffer from ARKit, on ARKit's own queue. All listener state lives on the
    /// main queue, so hop there: a request is never appended to while another thread replaces it.
    func append(_ buffer: CMSampleBuffer) {
        DispatchQueue.main.async { [weak self] in self?.appendOnMain(buffer) }
    }

    private func appendOnMain(_ buffer: CMSampleBuffer) {
        guard running, let request else { return }
        buffers += 1
        if buffers == 1 {
            log("first audio buffer arrived: \(CMSampleBufferGetFormatDescription(buffer).map { "\($0)" } ?? "no format")")
        }
        if Date().timeIntervalSince(lastReport) > 5 {
            log("audio buffers so far: \(buffers)")
            lastReport = Date()
        }
        request.appendAudioSampleBuffer(buffer)
        if Date().timeIntervalSince(startedAt) > 30 {
            restart()   // keep transcripts short
        }
    }

    private func restart() {
        task?.cancel()
        request?.endAudio()
        guard running, let recognizer else { return }

        let r = SFSpeechAudioBufferRecognitionRequest()
        r.requiresOnDeviceRecognition = true
        r.shouldReportPartialResults = true
        r.taskHint = .confirmation
        r.contextualStrings = ["go"]
        request = r
        heard = 0
        startedAt = Date()
        generation &+= 1
        let mine = generation

        task = recognizer.recognitionTask(with: r) { [weak self] result, error in
            DispatchQueue.main.async {
                // Cancelling an old task calls back with an error: ignore anything from old tasks.
                guard let self, mine == self.generation else { return }
                self.handle(result: result, error: error)
            }
        }
    }

    private var generation = 0

    private func handle(result: SFSpeechRecognitionResult?, error: Error?) {
        if let error {
            log("recogniser stopped: \(error.localizedDescription)")
        }
        if let result {
            let text = result.bestTranscription.formattedString
            if text != lastHeard, !text.isEmpty {
                lastHeard = text
                log("heard: \(text)")
                onHeard?(text)
            }
            let tokens = text
                .lowercased()
                .components(separatedBy: CharacterSet.letters.inverted)
            let count = tokens.filter { words.contains($0) }.count
            if count > heard {
                heard = count
                onYes?()
                restart()
                return
            }
        }
        if error != nil || (result?.isFinal ?? false) {
            let mine = generation
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
                guard let self, mine == self.generation else { return }
                self.restart()
            }
        }
    }
}
