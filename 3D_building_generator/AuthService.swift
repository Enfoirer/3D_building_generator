//
//  AuthService.swift
//  3D_building_generator
//
//  Created by Codex on 10/27/25.
//

import Foundation
import Auth0

enum AuthConfigurationError: LocalizedError {
    case fileMissing
    case invalidFormat
    case missingClientId
    case missingDomain

    var errorDescription: String? {
        switch self {
        case .fileMissing:
            return "Auth0 configuration file is missing."
        case .invalidFormat:
            return "Auth0 configuration file could not be parsed."
        case .missingClientId:
            return "Auth0 ClientId is not set."
        case .missingDomain:
            return "Auth0 Domain is not set."
        }
    }
}

struct AuthConfiguration {
    let clientId: String
    let domain: String
    let audience: String?
    let scheme: String

    static func load() throws -> AuthConfiguration {
        guard let url = Bundle.main.url(forResource: "Auth0", withExtension: "plist") else {
            throw AuthConfigurationError.fileMissing
        }

        guard let data = try? Data(contentsOf: url),
              let plist = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
            throw AuthConfigurationError.invalidFormat
        }

        let clientId = (plist["ClientId"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? (plist["A0ClientId"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)

        guard let resolvedClientId = clientId, !resolvedClientId.isEmpty else {
            throw AuthConfigurationError.missingClientId
        }

        let domain = (plist["Domain"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? (plist["A0Domain"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)

        guard let resolvedDomain = domain, !resolvedDomain.isEmpty else {
            throw AuthConfigurationError.missingDomain
        }

        let audience = (plist["Audience"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            ?? (plist["A0Audience"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)

        let scheme = Bundle.main.bundleIdentifier ?? "auth0"

        return AuthConfiguration(
            clientId: resolvedClientId,
            domain: resolvedDomain,
            audience: audience?.isEmpty == true ? nil : audience,
            scheme: scheme
        )
    }
}

final class AuthService {
    private let configuration: AuthConfiguration
    private let credentialsManager: CredentialsManager

    init(configuration: AuthConfiguration) {
        self.configuration = configuration

        let authentication = Auth0
            .authentication(clientId: configuration.clientId, domain: configuration.domain)
        self.credentialsManager = CredentialsManager(authentication: authentication)
    }

    func login() async throws -> Credentials {
        try await withCheckedThrowingContinuation { continuation in
            var webAuth = Auth0
                .webAuth(clientId: configuration.clientId, domain: configuration.domain)
                .scope("openid profile email offline_access")
                .useEphemeralSession()

            if let audience = configuration.audience {
                webAuth = webAuth.audience(audience)
            }

            webAuth.start { result in
                switch result {
                case .success(let credentials):
                    _ = self.credentialsManager.store(credentials: credentials)
                    continuation.resume(returning: credentials)
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    func retrieveStoredCredentials() async -> Credentials? {
        await withCheckedContinuation { continuation in
            guard credentialsManager.hasValid() else {
                continuation.resume(returning: nil)
                return
            }

            credentialsManager.credentials { result in
                switch result {
                case .success(let credentials):
                    continuation.resume(returning: credentials)
                case .failure:
                    continuation.resume(returning: nil)
                }
            }
        }
    }

    func clear() {
        _ = credentialsManager.clear()
    }

    func clearRemoteSession() async {
        await withCheckedContinuation { continuation in
            var webAuth = Auth0
                .webAuth(clientId: configuration.clientId, domain: configuration.domain)

            if let audience = configuration.audience {
                webAuth = webAuth.audience(audience)
            }

            webAuth.clearSession(federated: false) { _ in
                continuation.resume()
            }
        }
    }
}
