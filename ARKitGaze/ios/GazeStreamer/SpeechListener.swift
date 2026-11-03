import Foundation
import Speech

/// Listens for "yes" with Apple's Speech framework, fully on device (DESIGN_PLAN 3.5).
///
/// Audio comes from ARKit (`providesAudioData`), so nothing else touches the microphone.
/// Audio never leaves the phone: only a "yes" event is reported. If this phone cannot
/// recognise speech on device, the listener stays off rather than sending audio to a server.
final class SpeechListener {
    /// Words that count as "yes". Add "haan" or "okay" per person if needed.
    var words: Set<String> = ["yes"]
    var onYes: (() -> Void)?
    var onStatus: ((String) -> Void)?

    private let recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var heard = 0
    private var startedAt = Date()
    private var running = false

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
        guard isAvailable else {
            onStatus?("On-device speech is not available on this phone")
            return
        }
        running = true
        restart()
        onStatus?("Listening for \"yes\"")
    }

    func stop() {
        running = false
        task?.cancel()
        request?.endAudio()
        task = nil
        request = nil
        onStatus?("Speech off")
    }

    /// Called with each audio buffer from ARKit.
    func append(_ buffer: CMSampleBuffer) {
        guard running, let request else { return }
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
        r.contextualStrings = Array(words)
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
        if let result {
            let tokens = result.bestTranscription.formattedString
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
