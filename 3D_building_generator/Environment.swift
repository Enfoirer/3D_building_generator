//
//  Environment.swift
//  3D_building_generator
//
//  Created by Codex on 10/27/25.
//

import Foundation

enum AppEnvironment {
    struct API {
        static let baseURL: URL = {
            if let override = ProcessInfo.processInfo.environment["API_BASE_URL"], let url = URL(string: override) {
                return url
            }
            return URL(string: "http://127.0.0.1:8000")!
        }()
    }
}
