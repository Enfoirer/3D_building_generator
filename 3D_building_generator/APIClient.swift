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

        return try await send(request: request, expecting: expecting)
    }

    func uploadDataset(
        token: String,
        datasetName: String,
        notes: String?,
        photos: [UploadPhotoPayload]
    ) async throws -> UploadResponsePayload {
        guard !photos.isEmpty else {
            throw APIError(message: "Select at least one photo.", statusCode: nil)
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("uploads"))
        request.httpMethod = "POST"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let boundary = "Boundary-\(UUID().uuidString)"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.appendFormField(name: "dataset_name", value: datasetName, boundary: boundary)
        if let notes, !notes.isEmpty {
            body.appendFormField(name: "notes", value: notes, boundary: boundary)
        }
        for photo in photos {
            body.appendFileField(
                name: "files",
                filename: photo.filename,
                contentType: photo.mimeType,
                data: photo.data,
                boundary: boundary
            )
        }
        body.appendString("--\(boundary)--\r\n")

        request.httpBody = body

        do {
            let response: UploadResponsePayload = try await send(request: request, expecting: UploadResponsePayload.self)
            return response
        } catch {
            print("Upload dataset failed: \(error)")
            throw error
        }
    }

    private func send<T: Decodable>(request: URLRequest, expecting: T.Type) async throws -> T {
        let (data, response) = try await urlSession.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError(message: "Invalid response", statusCode: nil)
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError(message: message, statusCode: httpResponse.statusCode)
        }

        print("API response body:", String(data: data, encoding: .utf8) ?? "nil")

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

private extension Data {
    mutating func appendFormField(name: String, value: String, boundary: String) {
        appendString("--\(boundary)\r\n")
        appendString("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
        appendString("\(value)\r\n")
    }

    mutating func appendFileField(name: String, filename: String, contentType: String, data: Data, boundary: String) {
        appendString("--\(boundary)\r\n")
        appendString("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n")
        appendString("Content-Type: \(contentType)\r\n\r\n")
        append(data)
        appendString("\r\n")
    }

    mutating func appendString(_ string: String) {
        if let data = string.data(using: .utf8) {
            append(data)
        }
    }
}
