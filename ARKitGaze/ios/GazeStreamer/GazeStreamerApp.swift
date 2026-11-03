import SwiftUI

@main
struct GazeStreamerApp: App {
    @StateObject private var tracker = GazeTracker()

    var body: some Scene {
        WindowGroup {
            ContentView(tracker: tracker)
                .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        }
    }
}
