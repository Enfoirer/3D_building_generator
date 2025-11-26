//
//  _D_building_generatorApp.swift
//  3D_building_generator
//
//  Created by Xavier Yin on 10/27/25.
//

import SwiftUI

@main
struct _D_building_generatorApp: App {
    @StateObject private var appState = AppState()
#if canImport(UIKit)
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
#endif

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
        }
    }
}
