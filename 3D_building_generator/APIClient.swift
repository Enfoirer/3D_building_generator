//
//  APIClient.swift
//  3D_building_generator
//
//  Created by Codex on 10/27/25.
//

import Foundation

struct APIError: Error, LocalizedError {
    let message: String
    let statusCode: Int?

    var errorDescription: String? {
        if let statusCode {
            return "[\(statusCode)] \(message)"
        }
        return message
    }
}

struct APIClient {
    let baseURL: URL
    let urlSession: URLSession

    init(baseURL: URL = AppEnvironment.API.baseURL, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
    }

    func request<T: Decodable>(
        _ method: String,
        path: String,
        token: String,
        queryItems: [URLQueryItem]? = nil,
        body: Encodable? = nil,
        expecting: T.Type = T.self
    ) async throws -> T {
        var url = baseURL.appendingPathComponent(path)
        if let queryItems, var components = URLComponents(url: url, resolvingAgainstBaseURL: true) {
            components.queryItems = queryItems
            if let newURL = components.url {
                url = newURL
            }
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if let body {
            request.httpBody = try JSONEncoder.iso8601.encode(AnyEncodable(body))
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let (data, response) = try await urlSession.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError(message: "Invalid response", statusCode: nil)
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError(message: message, statusCode: httpResponse.statusCode)
        }

        if T.self == EmptyResponse.self {
            return EmptyResponse() as! T
        }

        do {
            return try JSONDecoder.iso8601.decode(T.self, from: data)
        } catch {
            throw APIError(message: "Decoding error: \(error)", statusCode: httpResponse.statusCode)
        }
    }
}

struct EmptyResponse: Decodable {}

extension JSONEncoder {
    static let iso8601: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()
}

extension JSONDecoder {
    static let iso8601: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}

private struct AnyEncodable: Encodable {
    private let encodeClosure: (Encoder) throws -> Void

    init<T: Encodable>(_ value: T) {
        encodeClosure = value.encode
    }

    func encode(to encoder: Encoder) throws {
        try encodeClosure(encoder)
    }
}
