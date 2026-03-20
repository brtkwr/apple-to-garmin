import SwiftUI

@main
struct HealthKitExporterApp: App {
    @StateObject private var healthKitManager = HealthKitManager()
    @StateObject private var httpServer = HTTPServer()

    var body: some Scene {
        WindowGroup {
            ContentView(healthKitManager: healthKitManager, httpServer: httpServer)
                .onAppear {
                    httpServer.healthKitManager = healthKitManager
                }
        }
    }
}
