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

struct UploadCreatePayload: Encodable {
    let datasetName: String
    let photoCount: Int
    let notes: String?

    enum CodingKeys: String, CodingKey {
        case datasetName = "dataset_name"
        case photoCount = "photo_count"
        case notes
    }
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
