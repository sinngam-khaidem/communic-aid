import SwiftUI

struct ContentView: View {
    @ObservedObject var tracker: GazeTracker

    @AppStorage("host") private var host = "192.168.1.34"
    @AppStorage("port") private var portText = "5005"

    var body: some View {
        VStack(spacing: 22) {
            Text("Gaze Streamer")
                .font(.largeTitle.bold())

            if !tracker.isSupported {
                Label("No TrueDepth face tracking on this device",
                      systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("Mac address").font(.caption).foregroundStyle(.secondary)
                TextField("192.168.1.25", text: $host)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.decimalPad)
                    .autocorrectionDisabled()

                Text("Port").font(.caption).foregroundStyle(.secondary)
                TextField("5005", text: $portText)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.numberPad)
            }
            .disabled(tracker.isRunning)

            Button(tracker.isRunning ? "Stop" : "Start streaming") {
                if tracker.isRunning {
                    tracker.stop()
                } else {
                    tracker.start(host: host, port: UInt16(portText) ?? 5005)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!tracker.isSupported)

            statusPanel

            Spacer()

            Text("Hold the phone steady beside the monitor, front camera facing you.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(28)
    }

    private var statusPanel: some View {
        VStack(spacing: 8) {
            HStack {
                Circle()
                    .fill(tracker.faceVisible ? .green : .gray)
                    .frame(width: 12, height: 12)
                Text(tracker.faceVisible ? "Face tracked" : "No face")
                    .font(.headline)
            }
            Text(tracker.status)
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            if tracker.isRunning {
                Grid(horizontalSpacing: 18, verticalSpacing: 4) {
                    GridRow {
                        Text("yaw").foregroundStyle(.secondary)
                        Text(String(format: "%+.1f°", tracker.yawDegrees)).monospacedDigit()
                    }
                    GridRow {
                        Text("pitch").foregroundStyle(.secondary)
                        Text(String(format: "%+.1f°", tracker.pitchDegrees)).monospacedDigit()
                    }
                    GridRow {
                        Text("packets").foregroundStyle(.secondary)
                        Text("\(tracker.packetsSent)").monospacedDigit()
                    }
                }
                .font(.system(.body, design: .monospaced))
            }
        }
        .padding()
        .frame(maxWidth: .infinity)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 12))
    }
}
