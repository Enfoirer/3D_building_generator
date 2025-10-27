//
//  AppState.swift
//  3D_building_generator
//
//  Created by Xavier Yin on 10/27/25.
//

import Foundation
import SwiftUI
import Combine
import Auth0
import JWTDecode

enum JobStatus: String, CaseIterable, Identifiable, Codable {
    case queued = "Queued"
    case processing = "Processing"
    case meshing = "Meshing"
    case texturing = "Texturing"
    case completed = "Completed"
    case failed = "Failed"

    var id: String { rawValue }

    var accentColor: Color {
        switch self {
        case .queued:
            return .gray
        case .processing, .meshing, .texturing:
            return .blue
        case .completed:
            return .green
        case .failed:
            return .red
        }
    }

    var iconName: String {
        switch self {
        case .queued:
            return "clock"
        case .processing:
            return "gearshape"
        case .meshing:
            return "cube"
        case .texturing:
            return "paintpalette"
        case .completed:
            return "checkmark.seal"
        case .failed:
            return "xmark.octagon"
        }
    }
}

struct UserSession: Identifiable, Codable {
    let id: String
    var name: String
    var email: String
    var pictureURL: URL?
}

struct ReconstructionJob: Identifiable, Codable {
    let id: UUID
    var datasetName: String
    var photoCount: Int
    var status: JobStatus
    var progress: Double
    var modelFileName: String?
    var createdAt: Date
    var updatedAt: Date
    var notes: String?
    var downloadEvents: [Date]
}

struct UploadRecord: Identifiable, Codable {
    let id: UUID
    let jobID: UUID
    var datasetName: String
    var submittedAt: Date
    var photoCount: Int
}

@MainActor
final class AppState: ObservableObject {
    @Published private(set) var currentUser: UserSession?
    @Published private(set) var credentials: Credentials?
    @Published var isAuthenticating = false
    @Published var authError: String?

    @Published var jobs: [ReconstructionJob]
    @Published var uploadRecords: [UploadRecord]

    private let authService: AuthService
    private let storage: AppStateStore

    init() {
        do {
            let configuration = try AuthConfiguration.load()
            self.authService = AuthService(configuration: configuration)
        } catch {
            fatalError("Auth0 configuration error: \(error.localizedDescription)")
        }
        self.storage = AppStateStore()

        if let snapshot = storage.loadSnapshot() {
            self.currentUser = snapshot.currentUser
            self.credentials = nil
            self.jobs = snapshot.jobs
            self.uploadRecords = snapshot.uploadRecords
        } else {
            let sampleJob = ReconstructionJob(
                id: UUID(),
                datasetName: "Campus Library",
                photoCount: 84,
                status: .processing,
                progress: 0.42,
                modelFileName: nil,
                createdAt: Date().addingTimeInterval(-3_600),
                updatedAt: Date(),
                notes: "Generating dense point cloud.",
                downloadEvents: []
            )

            let completedJob = ReconstructionJob(
                id: UUID(),
                datasetName: "Downtown Facade",
                photoCount: 126,
                status: .completed,
                progress: 1.0,
                modelFileName: "downtown_facade.glb",
                createdAt: Date().addingTimeInterval(-86_400 * 2),
                updatedAt: Date().addingTimeInterval(-2_700),
                notes: "Model optimized for AR preview.",
                downloadEvents: [
                    Date().addingTimeInterval(-3_600),
                    Date().addingTimeInterval(-900)
                ]
            )

            self.currentUser = nil
            self.credentials = nil
            self.jobs = [sampleJob, completedJob]
            self.uploadRecords = [
                UploadRecord(
                    id: UUID(),
                    jobID: sampleJob.id,
                    datasetName: sampleJob.datasetName,
                    submittedAt: sampleJob.createdAt,
                    photoCount: sampleJob.photoCount
                ),
                UploadRecord(
                    id: UUID(),
                    jobID: completedJob.id,
                    datasetName: completedJob.datasetName,
                    submittedAt: completedJob.createdAt,
                    photoCount: completedJob.photoCount
                )
            ]
            persistState()
        }

        Task {
            await restoreSession()
        }
    }

    func restoreSession() async {
        guard let credentials = await authService.retrieveStoredCredentials() else { return }

        apply(credentials: credentials)
    }

    func beginLogin() async {
        guard !isAuthenticating else { return }
        authError = nil
        isAuthenticating = true
        defer { isAuthenticating = false }

        do {
            let credentials = try await authService.login()
            apply(credentials: credentials)
        } catch {
            authError = error.localizedDescription
        }
    }

    func signOut() async {
        guard !isAuthenticating else { return }
        isAuthenticating = true
        defer { isAuthenticating = false }

        await authService.clearRemoteSession()
        authService.clear()

        credentials = nil
        currentUser = nil
        persistState()
    }

    func createUpload(datasetName: String, photoCount: Int, notes: String?) {
        let jobID = UUID()
        let now = Date()
        let job = ReconstructionJob(
            id: jobID,
            datasetName: datasetName,
            photoCount: photoCount,
            status: .queued,
            progress: 0,
            modelFileName: nil,
            createdAt: now,
            updatedAt: now,
            notes: notes,
            downloadEvents: []
        )

        jobs.insert(job, at: 0)

        let record = UploadRecord(
            id: UUID(),
            jobID: jobID,
            datasetName: datasetName,
            submittedAt: now,
            photoCount: photoCount
        )

        uploadRecords.insert(record, at: 0)
        persistState()
    }

    func markDownload(for jobID: UUID) {
        guard let index = jobs.firstIndex(where: { $0.id == jobID }) else { return }
        var job = jobs[index]
        job.downloadEvents.append(Date())
        job.updateStatus(job.status, progress: job.progress, modelFileName: job.modelFileName)
        jobs[index] = job
        persistState()
    }

    private func persistState() {
        let snapshot = AppStateSnapshot(
            currentUser: currentUser,
            jobs: jobs,
            uploadRecords: uploadRecords,
            savedAt: Date()
        )
        storage.save(snapshot: snapshot)
    }

    private func apply(credentials: Credentials) {
        self.credentials = credentials

        let token = credentials.idToken
        guard !token.isEmpty else {
            authError = "Auth0 did not return an ID token."
            return
        }

        do {
            let jwt = try decode(jwt: token)
            let subject = jwt.subject ?? UUID().uuidString
            let email = jwt["email"].string ?? ""
            let name = jwt["name"].string ?? jwt["nickname"].string ?? email
            let picture = jwt["picture"].string.flatMap(URL.init)

            currentUser = UserSession(
                id: subject,
                name: name.isEmpty ? "Creator" : name,
                email: email,
                pictureURL: picture
            )

            authError = nil
            persistState()
        } catch {
            authError = "Failed to decode id_token: \(error.localizedDescription)"
        }
    }
}

private extension ReconstructionJob {
    mutating func updateStatus(_ newStatus: JobStatus, progress: Double, modelFileName: String?) {
        status = newStatus
        self.progress = min(max(progress, 0), 1)
        self.modelFileName = modelFileName
        updatedAt = Date()
    }
}

struct AppStateSnapshot: Codable {
    var currentUser: UserSession?
    var jobs: [ReconstructionJob]
    var uploadRecords: [UploadRecord]
    var savedAt: Date
}

final class AppStateStore {
    private let fileURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(filename: String = "app_state.json") {
        let fm = FileManager.default
        let directory = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? fm.urls(for: .documentDirectory, in: .userDomainMask)[0]

        if !fm.fileExists(atPath: directory.path) {
            try? fm.createDirectory(at: directory, withIntermediateDirectories: true)
        }

        self.fileURL = directory.appendingPathComponent(filename)

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted]
        self.encoder = encoder

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    func loadSnapshot() -> AppStateSnapshot? {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return nil
        }

        do {
            let data = try Data(contentsOf: fileURL)
            return try decoder.decode(AppStateSnapshot.self, from: data)
        } catch {
#if DEBUG
            print("AppStateStore load error: \(error)")
#endif
            return nil
        }
    }

    func save(snapshot: AppStateSnapshot) {
        do {
            let data = try encoder.encode(snapshot)
            try data.write(to: fileURL, options: .atomic)
        } catch {
#if DEBUG
            print("AppStateStore save error: \(error)")
#endif
        }
    }

    func clear() {
        try? FileManager.default.removeItem(at: fileURL)
    }
}

#if DEBUG
extension AppState {
    static func previewState() -> AppState {
        let state = AppState()
        state.currentUser = UserSession(
            id: "auth0|preview",
            name: "Preview User",
            email: "preview@example.com",
            pictureURL: URL(string: "https://avatars.githubusercontent.com/u/1?v=4")
        )
        return state
    }
}
#endif
