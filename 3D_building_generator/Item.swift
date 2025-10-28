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
    case queued
    case processing
    case meshing
    case texturing
    case completed
    case failed

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .queued:
            return "Queued"
        case .processing:
            return "Processing"
        case .meshing:
            return "Meshing"
        case .texturing:
            return "Texturing"
        case .completed:
            return "Completed"
        case .failed:
            return "Failed"
        }
    }

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

    init(id: String, name: String, email: String, pictureURL: URL? = nil) {
        self.id = id
        self.name = name
        self.email = email
        self.pictureURL = pictureURL
    }
}

struct ReconstructionJob: Identifiable, Codable {
    let id: UUID
    var ownerID: String
    var datasetName: String
    var photoCount: Int
    var status: JobStatus
    var progress: Double
    var notes: String?
    var modelFileName: String?
    var createdAt: Date
    var updatedAt: Date
    var downloadEvents: [Date]

    enum CodingKeys: String, CodingKey {
        case id
        case ownerID = "owner_id"
        case datasetName = "dataset_name"
        case photoCount = "photo_count"
        case status
        case progress
        case notes
        case modelFileName = "model_file_name"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case downloadEvents = "download_events"
    }
}

struct UploadRecord: Identifiable, Codable {
    let id: UUID
    let jobID: UUID
    var datasetName: String
    var submittedAt: Date
    var photoCount: Int

    enum CodingKeys: String, CodingKey {
        case id
        case jobID = "job_id"
        case datasetName = "dataset_name"
        case submittedAt = "submitted_at"
        case photoCount = "photo_count"
    }
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
    private let apiClient: APIClient

    init() {
        do {
            let configuration = try AuthConfiguration.load()
            self.authService = AuthService(configuration: configuration)
        } catch {
            fatalError("Auth0 configuration error: \(error.localizedDescription)")
        }
        self.storage = AppStateStore()
        self.apiClient = APIClient()

        if let snapshot = storage.loadSnapshot() {
            self.currentUser = snapshot.currentUser
            self.credentials = nil
            self.jobs = snapshot.jobs
            self.uploadRecords = snapshot.uploadRecords
        } else {
            let ownerID = "local-preview-user"
            let sampleJob = ReconstructionJob(
                id: UUID(),
                ownerID: ownerID,
                datasetName: "Campus Library",
                photoCount: 84,
                status: .processing,
                progress: 0.42,
                notes: "Generating dense point cloud.",
                modelFileName: nil,
                createdAt: Date().addingTimeInterval(-3_600),
                updatedAt: Date(),
                downloadEvents: []
            )

            let completedJob = ReconstructionJob(
                id: UUID(),
                ownerID: ownerID,
                datasetName: "Downtown Facade",
                photoCount: 126,
                status: .completed,
                progress: 1.0,
                notes: "Model optimized for AR preview.",
                modelFileName: "downtown_facade.glb",
                createdAt: Date().addingTimeInterval(-86_400 * 2),
                updatedAt: Date().addingTimeInterval(-2_700),
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
        await refreshRemoteState()
    }

    func beginLogin() async {
        guard !isAuthenticating else { return }
        authError = nil
        isAuthenticating = true
        defer { isAuthenticating = false }

        do {
            let credentials = try await authService.login()
            apply(credentials: credentials)
            await refreshRemoteState()
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
        authError = nil
        jobs = []
        uploadRecords = []
        persistState()
        storage.clear()
    }

    @discardableResult
    func createUpload(datasetName: String, photoCount: Int, notes: String?) async -> Bool {
        guard let token = currentAccessToken() else {
            authError = "Missing access token."
            return false
        }

        let payload = UploadCreatePayload(datasetName: datasetName, photoCount: photoCount, notes: notes)

        do {
            let response: UploadResponsePayload = try await apiClient.request(
                "POST",
                path: "uploads",
                token: token,
                body: payload,
                expecting: UploadResponsePayload.self
            )

            merge(job: response.job)
            merge(upload: response.upload)
            persistState()
            authError = nil
            await refreshRemoteState()
            return true
        } catch {
            authError = error.localizedDescription
            return false
        }
    }

    @discardableResult
    func markDownload(for jobID: UUID) async -> Bool {
        guard let token = currentAccessToken() else {
            authError = "Missing access token."
            return false
        }

        let payload = DownloadLogPayload(jobID: jobID)

        do {
            let response: DownloadLogResponsePayload = try await apiClient.request(
                "POST",
                path: "downloads",
                token: token,
                body: payload,
                expecting: DownloadLogResponsePayload.self
            )

            merge(job: response.job)
            persistState()
            authError = nil
            return true
        } catch {
            authError = error.localizedDescription
            return false
        }
    }

    func syncWithServer() async {
        await refreshRemoteState()
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

    private func merge(job: ReconstructionJob) {
        if let index = jobs.firstIndex(where: { $0.id == job.id }) {
            jobs[index] = job
        } else {
            jobs.insert(job, at: 0)
        }
        jobs.sort { $0.createdAt > $1.createdAt }
    }

    private func merge(upload: UploadRecord) {
        if let index = uploadRecords.firstIndex(where: { $0.id == upload.id }) {
            uploadRecords[index] = upload
        } else {
            uploadRecords.insert(upload, at: 0)
        }
        uploadRecords.sort { $0.submittedAt > $1.submittedAt }
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

    private func currentAccessToken() -> String? {
        if let token = credentials?.accessToken, !token.isEmpty {
            return token
        }
        if let idToken = credentials?.idToken, !idToken.isEmpty {
            return idToken
        }
        return ProcessInfo.processInfo.environment["API_BEARER_TOKEN"]
    }

    private func refreshRemoteState() async {
        guard let token = currentAccessToken() else { return }

        do {
            let profile: APIUserProfile = try await apiClient.request(
                "GET",
                path: "me",
                token: token,
                expecting: APIUserProfile.self
            )

            let resolvedName = profile.name ?? currentUser?.name ?? profile.email ?? "Creator"
            let resolvedEmail = profile.email ?? currentUser?.email ?? ""
            let pictureURL = currentUser?.pictureURL
            currentUser = UserSession(id: profile.id, name: resolvedName, email: resolvedEmail, pictureURL: pictureURL)

            let uploadsResponse: UploadListResponsePayload = try await apiClient.request(
                "GET",
                path: "uploads",
                token: token,
                expecting: UploadListResponsePayload.self
            )

            let jobsResponse: JobsListResponsePayload = try await apiClient.request(
                "GET",
                path: "jobs",
                token: token,
                expecting: JobsListResponsePayload.self
            )

            jobs = jobsResponse.jobs.sorted { $0.createdAt > $1.createdAt }
            uploadRecords = uploadsResponse.uploads.sorted { $0.submittedAt > $1.submittedAt }
            persistState()
            authError = nil
        } catch {
            authError = error.localizedDescription
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
        state.jobs = state.jobs.map { job in
            var updated = job
            updated.ownerID = state.currentUser?.id ?? job.ownerID
            return updated
        }
        return state
    }
}
#endif
