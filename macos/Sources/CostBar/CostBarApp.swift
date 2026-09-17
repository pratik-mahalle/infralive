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
        let onboarding = args.contains("--onboarding")
        let model = AgentModel(start: false, fixture: onboarding ? nil : fixture, inboxFixture: inbox, awaitingConnection: onboarding)
        if args.contains("--session-expired") { model.recordFailure(BridgeError.authenticationRequired) }
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
        let bubble = args.contains("--bubble")
        let view = previewView(model: model, tab: tab, settings: settings, review: review, bubble: bubble).environment(\.colorScheme, dark ? .dark : .light)
        let host = NSHostingView(rootView: view)
        let bounds = NSRect(x: 0, y: 0, width: bubble ? 420 : (settings ? 550 : MenuPanel.width), height: bubble ? 280 : (settings ? (onboarding ? 580 : 720) : (onboarding ? min(520, MenuPanel.height) : MenuPanel.height)))
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
    static func previewView(model: AgentModel, tab: PanelTab, settings: Bool, review: ConnectionReview?, bubble: Bool) -> some View {
        if bubble {
            CompanionBubble(notice: CompanionNotice(id: "render", heading: CompanionNotice.preview.heading,
                detail: CompanionNotice.preview.detail, account: "Preview · Production · 123456789012",
                destination: AlertDestination(connectionID: "preview", feedID: "preview", sequences: [1])), review: {}, later: {}, dismiss: {})
        }
        else if settings { SettingsPanel(model: model, previewReview: review) }
        else { MenuPanel(model: model, initialTab: tab) }
    }
}

struct CostBarApp: App {
    @StateObject private var workspace = AccountWorkspace()

    var body: some Scene {
        MenuBarExtra {
            MenuPanel(model: workspace.selectedModel, workspace: workspace)
                .id(workspace.selectedID)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    workspace.shutdown()
                }
        } label: {
            WorkspaceMenuLabel(workspace: workspace)
        }
        .menuBarExtraStyle(.window)

        Window("Cloudwake Settings", id: "settings") {
            SettingsPanel(model: workspace.selectedModel, workspace: workspace).id(workspace.selectedID)
        }
        .windowResizability(.contentSize)

        Window("Ask Cost Agent", id: "ask") {
            AskPanel(model: workspace.selectedModel).id(workspace.selectedID)
        }
        .defaultSize(width: 640, height: 480)

        Window("Cloudwake Inbox", id: "alerts") {
            AlertReviewWindow(workspace: workspace)
        }
        .defaultSize(width: 440, height: 620)
    }
}

private struct WorkspaceMenuLabel: View {
    @ObservedObject var workspace: AccountWorkspace
    @Environment(\.openWindow) private var openWindow
    @State private var didCheckOnboarding = false

    var body: some View {
        Label {
            Text(workspace.selectedModel.menuLabel)
        } icon: {
            Image(nsImage: CloudwakeArtwork.menuImage)
        }
        .task {
            guard !didCheckOnboarding else { return }
            didCheckOnboarding = true
            if workspace.needsConnection {
                openWindow(id: "settings")
                NSApplication.shared.activate(ignoringOtherApps: true)
            }
        }
        .onReceive(workspace.$alertToReview) { destination in
            guard destination != nil else { return }
            openWindow(id: "alerts")
            NSApplication.shared.activate(ignoringOtherApps: true)
        }
    }
}

private struct AlertReviewWindow: View {
    @ObservedObject var workspace: AccountWorkspace
    var body: some View {
        if let target = workspace.alertToReview, let model = workspace.model(for: target.connectionID) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 10) {
                    CloudMascot(size: 44)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Let's take a look.").font(.headline)
                        Text(model.accountLabel ?? "AWS account").font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                }.padding(.horizontal, 20).padding(.top, 14)
                InboxView(model: model, requestedSequence: target.sequences.count == 1 ? target.sequences.first : nil)
                    .id(target.connectionID + target.feedID + target.sequences.description)
            }.frame(minWidth: 420, minHeight: 520).background { MacPanelBackground() }
        } else {
            QuietEmptyState(title: "This account isn't available", detail: "Open Cloudwake settings to connect the account again.", symbol: "cloud")
                .padding(24).frame(width: 420, height: 260)
        }
    }
}
