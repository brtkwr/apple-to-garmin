import CoreLocation
import Foundation
import HealthKit

@MainActor
final class HealthKitManager: ObservableObject {
    @Published var isAuthorised = false
    @Published var lastError: String?

    private let healthStore = HKHealthStore()

    // MARK: - Quantity types we care about

    static let quantityTypes: [HKQuantityTypeIdentifier] = [
        .heartRate,
        .runningPower,
        .runningSpeed,
        .runningStrideLength,
        .runningVerticalOscillation,
        .runningGroundContactTime,
        .distanceWalkingRunning,
        .distanceCycling,
        .activeEnergyBurned,
    ]

    // MARK: - Authorisation

    func requestAuthorisation() async {
        guard HKHealthStore.isHealthDataAvailable() else {
            lastError = "HealthKit is not available on this device"
            return
        }

        var typesToRead: Set<HKObjectType> = [
            HKObjectType.workoutType(),
            HKSeriesType.workoutRoute(),
        ]
        for id in Self.quantityTypes {
            if let qt = HKQuantityType.quantityType(forIdentifier: id) {
                typesToRead.insert(qt)
            }
        }

        do {
            try await healthStore.requestAuthorization(toShare: [], read: typesToRead)
            isAuthorised = true
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    // MARK: - Fetch all workouts

    func fetchWorkouts() async throws -> [HKWorkout] {
        let sortDescriptor = NSSortDescriptor(
            key: HKSampleSortIdentifierStartDate, ascending: false)
        return try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: HKObjectType.workoutType(),
                predicate: nil,
                limit: HKObjectQueryNoLimit,
                sortDescriptors: [sortDescriptor]
            ) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (samples as? [HKWorkout]) ?? [])
                }
            }
            healthStore.execute(query)
        }
    }

    // MARK: - Fetch quantity series (per-second resolution)

    func fetchQuantitySeries(
        for workout: HKWorkout,
        quantityType: HKQuantityType,
        unit: HKUnit
    ) async throws -> [[String: Any]] {
        let predicate = HKQuery.predicateForSamples(
            withStart: workout.startDate,
            end: workout.endDate,
            options: .strictStartDate
        )

        return try await withCheckedThrowingContinuation { continuation in
            var results: [[String: Any]] = []

            let query = HKQuantitySeriesSampleQuery(
                quantityType: quantityType,
                predicate: predicate
            ) { _, quantity, dateInterval, _, done, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }

                if let quantity, let dateInterval {
                    let value = quantity.doubleValue(for: unit)
                    let timestamp = dateInterval.start.timeIntervalSince1970
                    results.append([
                        "timestamp": timestamp,
                        "date": ISO8601DateFormatter().string(from: dateInterval.start),
                        "value": value,
                    ])
                }

                if done {
                    continuation.resume(returning: results)
                }
            }

            healthStore.execute(query)
        }
    }

    // MARK: - Fetch all metrics for a workout

    func fetchAllMetrics(for workout: HKWorkout) async throws -> [String: Any] {
        let metricConfigs: [(key: String, typeId: HKQuantityTypeIdentifier, unit: HKUnit)] = [
            ("heart_rate", .heartRate, HKUnit.count().unitDivided(by: .minute())),
            ("running_power", .runningPower, HKUnit.watt()),
            ("running_speed", .runningSpeed, HKUnit.meter().unitDivided(by: .second())),
            (
                "stride_length", .runningStrideLength,
                HKUnit.meter()
            ),
            (
                "vertical_oscillation", .runningVerticalOscillation,
                HKUnit.meterUnit(with: .centi)
            ),
            (
                "ground_contact_time", .runningGroundContactTime,
                HKUnit.secondUnit(with: .milli)
            ),
        ]

        var metrics: [String: Any] = [:]

        for config in metricConfigs {
            guard let quantityType = HKQuantityType.quantityType(forIdentifier: config.typeId)
            else { continue }

            do {
                let data = try await fetchQuantitySeries(
                    for: workout, quantityType: quantityType, unit: config.unit)
                if !data.isEmpty {
                    metrics[config.key] = data
                }
            } catch {
                // Skip metrics that aren't available for this workout
                continue
            }
        }

        // Include GPS route
        do {
            let route = try await fetchRoute(for: workout)
            if !route.isEmpty {
                metrics["route"] = route
            }
        } catch {
            // No route available for this workout
        }

        return metrics
    }

    // MARK: - Fetch workout route (GPS)

    func fetchRoute(for workout: HKWorkout) async throws -> [[String: Any]] {
        // First, get the HKWorkoutRoute objects associated with this workout
        let routeType = HKSeriesType.workoutRoute()
        let predicate = HKQuery.predicateForObjects(from: workout)

        let routes: [HKWorkoutRoute] = try await withCheckedThrowingContinuation { continuation in
            let query = HKSampleQuery(
                sampleType: routeType,
                predicate: predicate,
                limit: HKObjectQueryNoLimit,
                sortDescriptors: nil
            ) { _, samples, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (samples as? [HKWorkoutRoute]) ?? [])
                }
            }
            healthStore.execute(query)
        }

        guard let route = routes.first else {
            return []
        }

        // Then extract the CLLocation data from the route
        return try await withCheckedThrowingContinuation { continuation in
            var locations: [[String: Any]] = []
            let formatter = ISO8601DateFormatter()

            let query = HKWorkoutRouteQuery(route: route) { _, newLocations, done, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }

                if let newLocations {
                    for loc in newLocations {
                        locations.append([
                            "latitude": loc.coordinate.latitude,
                            "longitude": loc.coordinate.longitude,
                            "altitude": loc.altitude,
                            "timestamp": loc.timestamp.timeIntervalSince1970,
                            "date": formatter.string(from: loc.timestamp),
                            "horizontal_accuracy": loc.horizontalAccuracy,
                            "vertical_accuracy": loc.verticalAccuracy,
                            "speed": loc.speed,
                            "course": loc.course,
                        ])
                    }
                }

                if done {
                    continuation.resume(returning: locations)
                }
            }
            healthStore.execute(query)
        }
    }

    // MARK: - Serialise workout metadata

    func serialiseWorkout(_ workout: HKWorkout, index: Int) -> [String: Any] {
        let formatter = ISO8601DateFormatter()

        var result: [String: Any] = [
            "index": index,
            "start_date": formatter.string(from: workout.startDate),
            "end_date": formatter.string(from: workout.endDate),
            "duration_seconds": workout.duration,
            "activity_type": activityTypeName(workout.workoutActivityType),
            "activity_type_raw": workout.workoutActivityType.rawValue,
        ]

        // Total distance
        if let distance = workout.totalDistance {
            result["total_distance_metres"] = distance.doubleValue(for: .meter())
        }

        // Total energy
        if let energy = workout.totalEnergyBurned {
            result["total_energy_kcal"] = energy.doubleValue(for: .kilocalorie())
        }

        // Workout name from metadata
        if let name = workout.metadata?[HKMetadataKeyWorkoutBrandName] as? String {
            result["name"] = name
        }

        // Source
        result["source"] = workout.sourceRevision.source.name

        return result
    }

    private func activityTypeName(_ type: HKWorkoutActivityType) -> String {
        switch type {
        case .running: return "running"
        case .cycling: return "cycling"
        case .swimming: return "swimming"
        case .walking: return "walking"
        case .hiking: return "hiking"
        case .yoga: return "yoga"
        case .functionalStrengthTraining: return "strength_training"
        case .traditionalStrengthTraining: return "strength_training"
        case .crossTraining: return "cross_training"
        case .elliptical: return "elliptical"
        case .rowing: return "rowing"
        case .stairClimbing: return "stair_climbing"
        case .highIntensityIntervalTraining: return "hiit"
        case .jumpRope: return "jump_rope"
        case .pilates: return "pilates"
        case .dance: return "dance"
        case .cooldown: return "cooldown"
        case .coreTraining: return "core_training"
        default: return "other_\(type.rawValue)"
        }
    }
}
