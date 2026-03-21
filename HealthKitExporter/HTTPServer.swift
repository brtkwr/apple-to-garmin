import Foundation
import HealthKit
import Network

@MainActor
final class HTTPServer: ObservableObject {
    @Published var isRunning = false
    @Published var localIPAddress: String = "unknown"
    @Published var port: UInt16 = 8080
    @Published var logEntries: [LogEntry] = []

    var healthKitManager: HealthKitManager?

    private var listener: NWListener?
    private var cachedWorkouts: [HKWorkout]?

    struct LogEntry: Identifiable {
        let id = UUID()
        let timestamp = Date()
        let path: String
        let status: Int
        let detail: String
    }

    private func log(_ path: String, status: Int, detail: String = "") {
        logEntries.append(LogEntry(path: path, status: status, detail: detail))
    }

    func start() {
        // Stop any existing listener first
        listener?.cancel()
        listener = nil

        do {
            let params = NWParameters.tcp
            params.allowLocalEndpointReuse = true
            listener = try NWListener(using: params, on: NWEndpoint.Port(rawValue: port)!)
        } catch {
            print("Failed to create listener: \(error)")
            return
        }

        listener?.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in
                switch state {
                case .ready:
                    self?.isRunning = true
                    self?.localIPAddress = Self.getLocalIPAddress()
                    print("Server ready on port \(self?.port ?? 0)")
                case .failed(let error):
                    print("Server failed: \(error)")
                    self?.isRunning = false
                case .cancelled:
                    self?.isRunning = false
                default:
                    break
                }
            }
        }

        listener?.newConnectionHandler = { [weak self] connection in
            Task { @MainActor in
                self?.handleConnection(connection)
            }
        }

        listener?.start(queue: .global(qos: .userInitiated))
        localIPAddress = Self.getLocalIPAddress()
    }

    func stop() {
        listener?.cancel()
        listener = nil
        isRunning = false
        cachedWorkouts = nil
    }

    // MARK: - Connection handling

    private func handleConnection(_ connection: NWConnection) {
        connection.start(queue: .global(qos: .userInitiated))

        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) {
            [weak self] data, _, _, error in
            guard let self, let data, error == nil else {
                connection.cancel()
                return
            }

            guard let requestString = String(data: data, encoding: .utf8) else {
                self.sendResponse(connection: connection, status: 400, body: "Bad request")
                return
            }

            let lines = requestString.components(separatedBy: "\r\n")
            guard let requestLine = lines.first else {
                self.sendResponse(connection: connection, status: 400, body: "Bad request")
                return
            }

            let parts = requestLine.components(separatedBy: " ")
            guard parts.count >= 2 else {
                self.sendResponse(connection: connection, status: 400, body: "Bad request")
                return
            }

            let method = parts[0]
            let path = parts[1]

            guard method == "GET" else {
                self.sendResponse(
                    connection: connection, status: 405, body: "Method not allowed")
                return
            }

            Task { @MainActor in
                await self.routeRequest(path: path, connection: connection)
            }
        }
    }

    // MARK: - Routing

    @MainActor
    private func routeRequest(path: String, connection: NWConnection) async {
        if path == "/workouts" {
            await handleGetWorkouts(connection: connection)
            return
        }

        if let index = parseWorkoutSubpath(path: path, suffix: "metrics") {
            await handleGetMetrics(connection: connection, index: index)
            return
        }

        sendResponse(connection: connection, status: 404, body: "{\"error\": \"Not found\"}")
    }

    private func parseWorkoutSubpath(path: String, suffix: String) -> Int? {
        let pattern = "^/workouts/(\\d+)/\(suffix)$"
        guard let regex = try? NSRegularExpression(pattern: pattern),
            let match = regex.firstMatch(
                in: path, range: NSRange(path.startIndex..., in: path)),
            let range = Range(match.range(at: 1), in: path)
        else {
            return nil
        }
        return Int(path[range])
    }

    // MARK: - Handlers

    @MainActor
    private func handleGetWorkouts(connection: NWConnection) async {
        guard let manager = healthKitManager else {
            sendResponse(
                connection: connection, status: 500,
                body: "{\"error\": \"HealthKit not available\"}")
            return
        }

        do {
            let workouts = try await manager.fetchWorkouts()
            cachedWorkouts = workouts

            let serialised = workouts.enumerated().map { index, workout in
                manager.serialiseWorkout(workout, index: index)
            }

            log("/workouts", status: 200, detail: "\(workouts.count) workouts")
            sendJSONResponse(connection: connection, object: serialised)
        } catch {
            log("/workouts", status: 500, detail: error.localizedDescription)
            sendResponse(
                connection: connection, status: 500,
                body: "{\"error\": \"\(error.localizedDescription)\"}")
        }
    }

    @MainActor
    private func handleGetMetrics(connection: NWConnection, index: Int) async {
        guard let manager = healthKitManager else {
            sendResponse(
                connection: connection, status: 500,
                body: "{\"error\": \"HealthKit not available\"}")
            return
        }

        do {
            if cachedWorkouts == nil {
                cachedWorkouts = try await manager.fetchWorkouts()
            }

            guard let workouts = cachedWorkouts, index >= 0, index < workouts.count else {
                sendResponse(
                    connection: connection, status: 404,
                    body: "{\"error\": \"Workout not found at index \(index)\"}")
                return
            }

            let metrics = try await manager.fetchAllMetrics(for: workouts[index])
            let routeCount = (metrics["route"] as? [[String: Any]])?.count ?? 0
            let metricCount = metrics.values.compactMap { ($0 as? [[String: Any]])?.count }.reduce(0, +) - routeCount
            log("/workouts/\(index)/metrics", status: 200, detail: "\(metricCount) metrics, \(routeCount) GPS")
            sendJSONResponse(connection: connection, object: metrics)
        } catch {
            log("/workouts/\(index)/metrics", status: 500, detail: error.localizedDescription)
            sendResponse(
                connection: connection, status: 500,
                body: "{\"error\": \"\(error.localizedDescription)\"}")
        }
    }

    // MARK: - Response helpers

    private func sendJSONResponse(connection: NWConnection, object: Any) {
        do {
            let data = try JSONSerialization.data(
                withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
            let body = String(data: data, encoding: .utf8) ?? "[]"
            sendResponse(
                connection: connection, status: 200, body: body, contentType: "application/json")
        } catch {
            sendResponse(
                connection: connection, status: 500,
                body: "{\"error\": \"JSON serialisation failed\"}")
        }
    }

    private func sendResponse(
        connection: NWConnection, status: Int, body: String,
        contentType: String = "application/json"
    ) {
        let statusText: String
        switch status {
        case 200: statusText = "OK"
        case 400: statusText = "Bad Request"
        case 404: statusText = "Not Found"
        case 405: statusText = "Method Not Allowed"
        default: statusText = "Internal Server Error"
        }

        let bodyData = body.data(using: .utf8) ?? Data()
        let header =
            "HTTP/1.1 \(status) \(statusText)\r\n"
            + "Content-Type: \(contentType); charset=utf-8\r\n"
            + "Content-Length: \(bodyData.count)\r\n"
            + "Access-Control-Allow-Origin: *\r\n"
            + "Connection: close\r\n"
            + "\r\n"

        let responseData = (header.data(using: .utf8) ?? Data()) + bodyData

        connection.send(
            content: responseData,
            completion: .contentProcessed { _ in
                connection.cancel()
            })
    }

    // MARK: - IP address

    static func getLocalIPAddress() -> String {
        var address = "127.0.0.1"
        var ifaddr: UnsafeMutablePointer<ifaddrs>?

        guard getifaddrs(&ifaddr) == 0, let firstAddr = ifaddr else {
            return address
        }
        defer { freeifaddrs(ifaddr) }

        for ptr in sequence(first: firstAddr, next: { $0.pointee.ifa_next }) {
            let interface = ptr.pointee
            let addrFamily = interface.ifa_addr.pointee.sa_family

            guard addrFamily == UInt8(AF_INET) else { continue }

            let name = String(cString: interface.ifa_name)
            guard name == "en0" else { continue }

            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(
                interface.ifa_addr, socklen_t(interface.ifa_addr.pointee.sa_len),
                &hostname, socklen_t(hostname.count),
                nil, 0, NI_NUMERICHOST)

            address = String(cString: hostname)
            break
        }

        return address
    }
}
