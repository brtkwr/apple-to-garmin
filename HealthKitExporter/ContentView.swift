import SwiftUI

struct ContentView: View {
    @ObservedObject var healthKitManager: HealthKitManager
    @ObservedObject var httpServer: HTTPServer

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                // Status indicator
                VStack(spacing: 8) {
                    Circle()
                        .fill(httpServer.isRunning ? Color.green : Color.red)
                        .frame(width: 20, height: 20)
                        .shadow(color: httpServer.isRunning ? .green.opacity(0.5) : .clear, radius: 8)

                    Text(httpServer.isRunning ? "Server Running" : "Server Stopped")
                        .font(.headline)
                        .foregroundStyle(httpServer.isRunning ? .primary : .secondary)
                }

                // Connection info
                if httpServer.isRunning {
                    VStack(spacing: 4) {
                        Text("Connect to:")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)

                        Text("http://\(httpServer.localIPAddress):\(httpServer.port)")
                            .font(.system(.body, design: .monospaced))
                            .textSelection(.enabled)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(Color(.systemGray6))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Endpoints:")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)

                        Group {
                            Text("GET /workouts")
                            Text("GET /workouts/{index}/heart_rate")
                            Text("GET /workouts/{index}/metrics")
                        }
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .padding(.horizontal)
                }

                Spacer()

                // HealthKit status
                if !healthKitManager.isAuthorised {
                    Button("Authorise HealthKit") {
                        Task {
                            await healthKitManager.requestAuthorisation()
                        }
                    }
                    .buttonStyle(.bordered)
                }

                if let error = healthKitManager.lastError {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }

                // Server toggle
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
                    Text(httpServer.isRunning ? "Stop Server" : "Start Server")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 4)
                }
                .buttonStyle(.borderedProminent)
                .tint(httpServer.isRunning ? .red : .blue)
                .padding(.horizontal, 40)
                .padding(.bottom, 32)
            }
            .navigationTitle("HealthKit Exporter")
        }
    }
}

#Preview {
    ContentView(
        healthKitManager: HealthKitManager(),
        httpServer: HTTPServer()
    )
}
