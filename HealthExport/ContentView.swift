import SwiftUI

struct ContentView: View {
    @ObservedObject var healthKitManager: HealthKitManager
    @ObservedObject var httpServer: HTTPServer

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                // Status + connection info
                HStack(spacing: 12) {
                    Circle()
                        .fill(httpServer.isRunning ? Color.green : Color.red)
                        .frame(width: 12, height: 12)

                    if httpServer.isRunning {
                        Text("http://\(httpServer.localIPAddress):\(String(httpServer.port))")
                            .font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled)
                    } else {
                        Text("Server stopped")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Button {
                        if httpServer.isRunning {
                            httpServer.stop()
                        } else {
                            if !healthKitManager.isAuthorised {
                                Task {
                                    await healthKitManager.requestAuthorisation()
                                    httpServer.start()
                                }
                            } else {
                                httpServer.start()
                            }
                        }
                    } label: {
                        Text(httpServer.isRunning ? "Stop" : "Start")
                            .font(.caption)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(httpServer.isRunning ? .red : .blue)
                }
                .padding(.horizontal)

                if let error = healthKitManager.lastError {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                // Request log
                List(httpServer.logEntries.reversed()) { entry in
                    HStack {
                        Text(entry.timestamp, format: .dateTime.hour().minute().second())
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)

                        Text("\(entry.status)")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(entry.status == 200 ? .green : .red)

                        Text(entry.path)
                            .font(.system(.caption2, design: .monospaced))
                            .lineLimit(1)

                        Spacer()

                        if !entry.detail.isEmpty {
                            Text(entry.detail)
                                .font(.system(.caption2, design: .monospaced))
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .listStyle(.plain)
            }
            .navigationTitle("Health Export")
            .navigationBarTitleDisplayMode(.inline)
            .onChange(of: httpServer.isRunning) { _, running in
                UIApplication.shared.isIdleTimerDisabled = running
            }
        }
    }
}

#Preview {
    ContentView(
        healthKitManager: HealthKitManager(),
        httpServer: HTTPServer()
    )
}
