import AppKit
import SwiftUI

@main
enum CostBarLauncher {
    @MainActor
    static func main() {
        if CommandLine.arguments.contains("--check-bundle") {
            do {
                var settings = AgentSettings.initial
                guard settings.dataPath != nil else { throw BridgeError.message("No bundled runtime found") }
                let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("cloudwake-check-\(UUID())")
                defer { try? FileManager.default.removeItem(at: temporary) }
                settings.dataPath = temporary.path
                let process = try settings.makeProcess(["demo"])
                try process.run()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else { throw BridgeError.message("Bundled demo failed") }
                print("Cloudwake bundled runtime verified without AWS access.")
            } catch { fputs("Bundle check failed: \(error)\n", stderr); exit(1) }
            return
        }
        if CommandLine.arguments.contains("--render") {
            do { try renderPreview() }
            catch { fputs("Preview failed: \(error)\n", stderr); exit(1) }
            return
        }
        CostBarApp.main()
    }

    @MainActor
    static func renderPreview() throws {
        let args = CommandLine.arguments
        guard let flag = args.firstIndex(of: "--render"), args.count > flag + 2 else {
            throw BridgeError.message("Usage: CostBar --render OUTPUT.png STATUS.json [--dark]")
        }
        _ = NSApplication.shared
        NSApplication.shared.setActivationPolicy(.accessory)
        let fixture = try AgentStatus.decode(Data(contentsOf: URL(fileURLWithPath: args[flag + 2])))
        var inbox: InboxPage?
        if let flag = args.firstIndex(of: "--inbox-data"), args.count > flag + 1 {
            inbox = try InboxPage.decode(Data(contentsOf: URL(fileURLWithPath: args[flag + 1])))
        }
        let model = AgentModel(start: false, fixture: fixture, inboxFixture: inbox)
        let dark = args.contains("--dark")
        NSApplication.shared.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        let tab: PanelTab = args.contains("--inbox") ? .inbox : (args.contains("--changes") ? .changes : (args.contains("--savings") ? .savings : .overview))
        let settings = args.contains("--settings")
        var review: ConnectionReview?
        if let flag = args.firstIndex(of: "--connection-review"), args.count > flag + 1 {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            review = try decoder.decode(ConnectionReview.self, from: Data(contentsOf: URL(fileURLWithPath: args[flag + 1])))
        }
        let view = previewView(model: model, tab: tab, settings: settings, review: review).environment(\.colorScheme, dark ? .dark : .light)
        let host = NSHostingView(rootView: view)
        let bounds = NSRect(x: 0, y: 0, width: settings ? 550 : MenuPanel.width, height: settings ? 720 : MenuPanel.height)
        let window = NSWindow(contentRect: bounds,
                              styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host
        window.setFrame(bounds, display: true)
        host.frame = window.contentView!.bounds
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.5))
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
            throw BridgeError.message("Unable to allocate preview image")
        }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else {
            throw BridgeError.message("Unable to encode preview")
        }
        try data.write(to: URL(fileURLWithPath: args[flag + 1]))
    }

    @MainActor @ViewBuilder
    static func previewView(model: AgentModel, tab: PanelTab, settings: Bool, review: ConnectionReview?) -> some View {
        if settings { SettingsPanel(model: model, previewReview: review) }
        else { MenuPanel(model: model, initialTab: tab) }
    }
}

struct CostBarApp: App {
    @StateObject private var model = AgentModel()

    var body: some Scene {
        MenuBarExtra {
            MenuPanel(model: model)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    model.shutdown()
                }
        } label: {
            Label {
                Text(model.menuLabel)
            } icon: {
                Image(nsImage: CloudwakeArtwork.menuImage)
            }
        }
        .menuBarExtraStyle(.window)

        Window("Cloudwake Settings", id: "settings") {
            SettingsPanel(model: model)
        }
        .windowResizability(.contentSize)

        Window("Ask Cost Agent", id: "ask") {
            AskPanel(model: model)
        }
        .defaultSize(width: 640, height: 480)
    }
}
