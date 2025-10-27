//
//  Item.swift
//  3D_building_generator
//
//  Created by Xavier Yin on 10/27/25.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
