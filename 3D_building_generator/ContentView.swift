//
//  ContentView.swift
//  3D_building_generator
//
//  Created by Xavier Yin on 10/27/25.
//

import SwiftUI
import PhotosUI

struct ContentView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        Group {
            if appState.currentUser == nil {
                LoginView()
            } else {
                AuthenticatedRootView()
            }
        }
        .animation(.easeInOut, value: appState.currentUser?.id)
    }
}

private struct LoginView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                VStack(spacing: 12) {
                    Text("3D Building Generator")
                        .font(.largeTitle.bold())
                        .multilineTextAlignment(.center)
                    Text("Sign in with Auth0 to manage uploads and 3D reconstructions.")
                        .font(.body)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                }

                if let error = appState.authError {
                    Text(error)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }

                Button {
                    Task {
                        await appState.beginLogin()
                    }
                } label: {
                    Group {
                        if appState.isAuthenticating {
                            ProgressView()
                                .progressViewStyle(.circular)
                                .tint(.white)
                        } else {
                            Label("Continue with Auth0", systemImage: "person.crop.circle.badge.checkmark")
                                .font(.headline)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(RoundedRectangle(cornerRadius: 14).fill(Color.accentColor))
                    .foregroundStyle(.white)
                    .padding(.horizontal)
                }
                .disabled(appState.isAuthenticating)

                Spacer()

                Text("Uploads are processed securely. By continuing you agree to our storage policies.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
                    .padding(.bottom)
            }
            .navigationTitle("Welcome")
        }
    }
}

private struct AuthenticatedRootView: View {
    @EnvironmentObject private var appState: AppState
    var body: some View {
        TabView {
            DashboardView()
                .tabItem {
                    Label("Overview", systemImage: "rectangle.grid.2x2")
                }

            UploadView()
                .tabItem {
                    Label("Upload", systemImage: "square.and.arrow.up")
                }

            HistoryView()
                .tabItem {
                    Label("History", systemImage: "clock.arrow.circlepath")
                }

            AccountView()
                .tabItem {
                    Label("Account", systemImage: "person.crop.circle")
                }
        }
        .task {
            await appState.syncWithServer()
        }
    }
}

private struct DashboardView: View {
    @EnvironmentObject private var appState: AppState

    private var activeJobs: [ReconstructionJob] {
        appState.jobs.filter { job in
            job.status != .completed && job.status != .failed
        }
    }

    private var completedJobs: [ReconstructionJob] {
        appState.jobs.filter { $0.status == .completed }
    }

    var body: some View {
        NavigationStack {
            List {
                Section("Active jobs") {
                    if activeJobs.isEmpty {
                        Text("No active jobs right now. Submit a new dataset to kick off processing.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 8)
                    } else {
                        ForEach(activeJobs) { job in
                            JobRow(job: job)
                        }
                    }
                }

                Section("Completed models") {
                    if completedJobs.isEmpty {
                        Text("Completed models will show up here. Revisit once a job finishes.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .padding(.vertical, 8)
                    } else {
                        ForEach(completedJobs) { job in
                            JobRow(job: job) {
                                await appState.markDownload(for: job.id)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Overview")
        }
    }
}

private struct JobRow: View {
    let job: ReconstructionJob
    var downloadAction: (() async -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(job.datasetName)
                    .font(.headline)
                Spacer()
                JobStatusBadge(status: job.status)
            }

            Text("\(job.photoCount) photos · \(job.createdAt.relativeDescription)")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if job.status != .completed && job.status != .failed {
                ProgressView(value: job.progress) {
                    Text(progressLabel)
                }
                .progressViewStyle(.linear)
            } else if job.status == .completed, let fileName = job.modelFileName {
                HStack(spacing: 8) {
                    Image(systemName: "shippingbox.and.arrow.down")
                    Text(fileName)
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }

            if job.status == .completed, let action = downloadAction {
                Button {
                    Task {
                        await action()
                    }
                } label: {
                    Label("Download model", systemImage: "arrow.down.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.accentColor)
                .padding(.top, 6)
            }

            if let notes = job.notes, !notes.isEmpty {
                Text(notes)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .padding(.top, 4)
            }
        }
        .padding(.vertical, 4)
    }

    private var progressLabel: String {
        let percentage = Int(job.progress * 100)
        switch job.status {
        case .processing:
            return "Running SfM · \(percentage)%"
        case .meshing:
            return "Meshing geometry · \(percentage)%"
        case .texturing:
            return "Baking textures · \(percentage)%"
        default:
            return "\(percentage)% complete"
        }
    }
}

private struct JobStatusBadge: View {
    let status: JobStatus

    var body: some View {
        Label(status.rawValue, systemImage: status.iconName)
        Label(status.displayName, systemImage: status.iconName)
            .font(.caption)
            .bold()
            .padding(.vertical, 6)
            .padding(.horizontal, 10)
            .background(status.accentColor.opacity(0.15))
            .foregroundStyle(status.accentColor)
            .clipShape(Capsule())
    }
}

private struct UploadView: View {
    @EnvironmentObject private var appState: AppState
    @State private var datasetName = ""
    @State private var notes = ""
    @State private var selectedItems: [PhotosPickerItem] = []
    @State private var showSuccessBanner = false
    @State private var recentlySubmittedName = ""
    @State private var isSubmitting = false
    @State private var submitError: String?

    private var canSubmit: Bool {
        !datasetName.trimmingCharacters(in: .whitespaces).isEmpty && !selectedItems.isEmpty
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Dataset details") {
                    TextField("Project name", text: $datasetName)
                    TextEditor(text: $notes)
                        .frame(minHeight: 80)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.gray.opacity(0.2))
                        )
                        .listRowInsets(EdgeInsets())
                        .padding(.vertical, 4)
                }

                Section("Photos") {
                    PhotosPicker(selection: $selectedItems, maxSelectionCount: 200, matching: .images) {
                        Label("Choose photos", systemImage: "photo.on.rectangle")
                    }

                    if selectedItems.isEmpty {
                        Text("Select at least 20 high-quality images for best results.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        Text("\(selectedItems.count) photos selected")
                            .font(.subheadline)
                    }
                }

                Section("Submit") {
                    if let submitError {
                        Text(submitError)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    Button {
                        Task {
                            await submitUpload()
                        }
                    } label: {
                        if isSubmitting {
                            ProgressView()
                                .frame(maxWidth: .infinity, alignment: .center)
                        } else {
                            Label("Submit dataset", systemImage: "paperplane.fill")
                                .frame(maxWidth: .infinity, alignment: .center)
                        }
                    }
                    .disabled(!canSubmit || isSubmitting)
                }
            }
            .navigationTitle("New Upload")
            .alert("Upload queued", isPresented: $showSuccessBanner) {
                Button("OK", role: .cancel) { }
            } message: {
                Text("Your dataset “\(recentlySubmittedName)” has been queued for reconstruction. Check the overview tab for live status.")
            }
        }
    }

    private func submitUpload() async {
        guard canSubmit else { return }
        isSubmitting = true
        submitError = nil
        let trimmedName = datasetName.trimmingCharacters(in: .whitespaces)
        let success = await appState.createUpload(
            datasetName: trimmedName,
            photoCount: selectedItems.count,
            notes: notes.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        isSubmitting = false

        guard success else {
            submitError = appState.authError ?? "Failed to submit dataset."
            return
        }

        recentlySubmittedName = trimmedName
        datasetName = ""
        notes = ""
        selectedItems.removeAll()
        showSuccessBanner = true
    }
}

private struct HistoryView: View {
    @EnvironmentObject private var appState: AppState

    private var downloadJobs: [ReconstructionJob] {
        appState.jobs.filter { !$0.downloadEvents.isEmpty }
    }

    var body: some View {
        NavigationStack {
            List {
                Section("Upload history") {
                    if appState.uploadRecords.isEmpty {
                        Text("Upload activity will appear here.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(appState.uploadRecords) { record in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(record.datasetName)
                                    .font(.headline)
                                Text("\(record.photoCount) photos · submitted \(record.submittedAt.relativeDescription)")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }

                Section("Download activity") {
                    if downloadJobs.isEmpty {
                        Text("Downloads will appear once a model is retrieved.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(downloadJobs) { job in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(job.datasetName)
                                    .font(.headline)
                                Text("Downloaded \(job.downloadEvents.count) time(s)")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)

                                ForEach(job.downloadEvents.sorted(by: >), id: \.self) { event in
                                    Text("• \(event.timestampDescription)")
                                        .font(.footnote)
                                        .foregroundStyle(.secondary)
                                }

                                Button {
                                    Task {
                                        _ = await appState.markDownload(for: job.id)
                                    }
                                } label: {
                                    Label("Log new download", systemImage: "arrow.down.circle")
                                }
                                .buttonStyle(.bordered)
                                .padding(.top, 4)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
            }
            .navigationTitle("History")
        }
    }
}

private struct AccountView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        NavigationStack {
            List {
                if let user = appState.currentUser {
                    Section("Profile") {
                        if let pictureURL = user.pictureURL {
                            HStack {
                                Spacer()
                                AsyncImage(url: pictureURL) { phase in
                                    switch phase {
                                    case .empty:
                                        ProgressView()
                                    case .success(let image):
                                        image
                                            .resizable()
                                            .aspectRatio(contentMode: .fill)
                                            .frame(width: 72, height: 72)
                                            .clipShape(Circle())
                                    case .failure:
                                        Image(systemName: "person.crop.circle")
                                            .resizable()
                                            .scaledToFit()
                                            .frame(width: 72, height: 72)
                                            .foregroundStyle(.secondary)
                                    @unknown default:
                                        EmptyView()
                                    }
                                }
                                Spacer()
                            }
                            .padding(.vertical, 8)
                        }

                        LabeledContent("Name", value: user.name)
                        LabeledContent("Email", value: user.email)
                    }
                }

                Section("Session") {
                    Button(role: .destructive) {
                        Task {
                            await appState.signOut()
                        }
                    } label: {
                        Label("Sign out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                    .disabled(appState.isAuthenticating)
                }
            }
            .navigationTitle("Account")
        }
    }
}

private extension Date {
    private static let relativeFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter
    }()

    private static let timestampFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter
    }()

    var relativeDescription: String {
        Date.relativeFormatter.localizedString(for: self, relativeTo: Date())
    }

    var timestampDescription: String {
        Date.timestampFormatter.string(from: self)
    }
}

#Preview {
    ContentView()
        .environmentObject(AppState.previewState())
}
