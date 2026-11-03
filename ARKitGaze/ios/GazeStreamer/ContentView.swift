import SwiftUI

struct ContentView: View {
    @ObservedObject var streamer: Streamer
    @ObservedObject var sensor: FaceSensor

    @AppStorage("host") private var host = "192.168.1.34"
    @AppStorage("port") private var portText = "5005"
    @AppStorage("listen") private var listen = true

    var body: some View {
        VStack(spacing: 22) {
            Text("Gaze Streamer")
                .font(.largeTitle.bold())

            if !sensor.isSupported {
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

                Toggle("Listen for \"yes\"", isOn: $listen)
            }
            .disabled(sensor.isRunning)

            Button(sensor.isRunning ? "Stop" : "Start streaming") {
                if sensor.isRunning {
                    streamer.stop()
                } else {
                    streamer.start(host: host, port: UInt16(portText) ?? 5005, listen: listen)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!sensor.isSupported)

            statusPanel

            Spacer()

            Text("Fix the phone below the screen, front camera facing you, 40 to 60 cm away.")
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
                    .fill(sensor.faceVisible ? .green : .gray)
                    .frame(width: 12, height: 12)
                Text(sensor.faceVisible ? "Face tracked" : "No face")
                    .font(.headline)
            }
            Text(streamer.error ?? sensor.status)
                .font(.caption)
                .foregroundStyle(streamer.error == nil ? Color.secondary : Color.red)
                .multilineTextAlignment(.center)
            Text(streamer.speechStatus)
                .font(.caption)
                .foregroundStyle(.secondary)

            if sensor.isRunning {
                Grid(horizontalSpacing: 18, verticalSpacing: 4) {
                    GridRow {
                        Text("yaw").foregroundStyle(.secondary)
                        Text(String(format: "%+.1f°", sensor.yawDegrees)).monospacedDigit()
                    }
                    GridRow {
                        Text("pitch").foregroundStyle(.secondary)
                        Text(String(format: "%+.1f°", sensor.pitchDegrees)).monospacedDigit()
                    }
                    GridRow {
                        Text("brows").foregroundStyle(.secondary)
                        Text(String(format: "%.2f", sensor.browLevel)).monospacedDigit()
                    }
                    GridRow {
                        Text("frames").foregroundStyle(.secondary)
                        Text("\(sensor.framesSent)").monospacedDigit()
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
