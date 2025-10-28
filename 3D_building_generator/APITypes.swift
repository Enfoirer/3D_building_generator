//
//  APITypes.swift
//  3D_building_generator
//
//  Created by Codex on 10/27/25.
//

import Foundation

struct APIUserProfile: Decodable {
    let id: String
    let email: String?
    let name: String?
}

struct UploadResponsePayload: Decodable {
    let upload: UploadRecord
    let job: ReconstructionJob
}

struct UploadListResponsePayload: Decodable {
    let uploads: [UploadRecord]
}

struct JobsListResponsePayload: Decodable {
    let jobs: [ReconstructionJob]
}

struct DownloadLogPayload: Encodable {
    let jobID: UUID

    enum CodingKeys: String, CodingKey {
        case jobID = "job_id"
    }
}

struct DownloadLogResponsePayload: Decodable {
    let job: ReconstructionJob
}

struct UploadPhotoPayload {
    let filename: String
    let data: Data
    let mimeType: String
}
