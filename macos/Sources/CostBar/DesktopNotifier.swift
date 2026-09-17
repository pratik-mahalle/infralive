import CryptoKit
import Foundation
import UserNotifications
import Combine
import AppKit

struct DesktopAlert: Decodable {
    let sequence: Int
    let kind: String
    let title: String
    let body: String
}

struct AlertPage: Decodable {
    let alerts: [DesktopAlert]
    let nextCursor: Int
    static func decode(_ data: Data) throws -> AlertPage {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(AlertPage.self, from: data)
    }
}

struct DesktopMessage {
    let sequence: Int
    let title: String
    let body: String
}

enum NotificationPlan {
    static func messages(_ alerts: [DesktopAlert], demo: Bool) -> [DesktopMessage] {
        let prefix = demo ? "[Demo] " : ""
        if alerts.count > 3 {
            let creations = alerts.filter { $0.kind == "event" }.count
            let idle = alerts.filter { $0.kind == "idle" }.count
            let spending = alerts.count - creations - idle
            return [DesktopMessage(sequence: alerts.last!.sequence,
                title: "\(prefix)\(alerts.count) AWS alerts",
                body: "\(creations) resource changes · \(idle) idle-resource alerts · \(spending) spending alerts. Open Cloudwake for the evidence.")]
        }
        return alerts.map { DesktopMessage(sequence: $0.sequence, title: prefix + $0.title,
                                            body: String($0.body.prefix(600))) }
    }

    static func key(database: String, demo: Bool, account: String) -> String {
        let input = "\(database)|\(demo)|\(account)"
        return SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

@MainActor
final class DesktopNotifier: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
    @Published private(set) var enabled = UserDefaults.standard.bool(forKey: "CostBar.desktop.enabled")
    @Published private(set) var permission = "Not enabled"
    @Published private(set) var lastError: String?
    @Published var companionEnabled = UserDefaults.standard.object(forKey: "Cloudwake.companion.enabled") as? Bool ?? true {
        didSet {
            defaults.set(companionEnabled, forKey: "Cloudwake.companion.enabled")
            if !companionEnabled { companion.clear() }
        }
    }
    let companion = CompanionPresenter()
    private let defaults = UserDefaults.standard
    // Do not instantiate Notification Center in unsigned test / render executables.
    private var center: UNUserNotificationCenter { UNUserNotificationCenter.current() }

    override init() {
        super.init()
        // Install before async account loading so a notification click at launch is retained.
        if Bundle.main.bundleIdentifier == "dev.aws-cost-agent.CostBar" && !CommandLine.arguments.contains("--render") {
            center.delegate = self
        }
    }

    func checkPermission() async {
        guard Bundle.main.bundleIdentifier == "dev.aws-cost-agent.CostBar" else { return }
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional: permission = enabled ? "Enabled" : "Paused"
        case .denied: permission = "Blocked in macOS Settings"
        case .notDetermined: permission = "Permission not requested"
        default: permission = "Unavailable"
        }
        center.delegate = self
    }

    func enable(status: AgentStatus) async {
        do {
            let allowed = try await center.requestAuthorization(options: [.alert, .sound])
            guard allowed else { await checkPermission(); return }
            // Start at the current high-water mark. Enabling doesn't replay old alerts.
            let key = namespace(status)
            defaults.set(status.notificationCursor ?? 0, forKey: cursorKey(key))
            enabled = true
            defaults.set(true, forKey: "CostBar.desktop.enabled")
            lastError = nil
            await checkPermission()
        } catch { lastError = error.localizedDescription }
    }

    func disable() {
        enabled = false
        defaults.set(false, forKey: "CostBar.desktop.enabled")
        permission = "Paused"
        companion.clear()
    }

    func namespace(_ status: AgentStatus) -> String {
        NotificationPlan.key(database: status.paths.database, demo: status.demo,
                             account: status.notificationFeedId ?? "legacy")
    }

    private func cursorKey(_ key: String) -> String { "CostBar.desktop.cursor." + key }

    func cursor(for status: AgentStatus) -> Int {
        let key = cursorKey(namespace(status))
        if defaults.object(forKey: key) == nil {
            defaults.set(status.notificationCursor ?? 0, forKey: key)
        }
        return defaults.integer(forKey: key)
    }

    func publish(_ page: AlertPage, status: AgentStatus, accountLabel: String? = nil, connectionID: String? = nil) async throws {
        guard enabled, !page.alerts.isEmpty else { return }
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            await checkPermission()
            throw BridgeError.message("Allow Cloudwake notifications in macOS System Settings.")
        }
        let namespace = namespace(status)
        for message in NotificationPlan.messages(page.alerts, demo: status.demo) {
            let content = UNMutableNotificationContent()
            let grouped = page.alerts.count > 3
            let kind = page.alerts.first(where: { $0.sequence == message.sequence })?.kind ?? "alert"
            content.title = (status.demo ? "[Demo] " : "") + CompanionNotice.heading(kind: kind, count: grouped ? page.alerts.count : 1)
            content.subtitle = accountLabel ?? status.snapshot.map { "AWS account " + $0.accountId } ?? ""
            content.body = grouped ? message.body : String(message.title.prefix(180))
            if let connectionID, let feedID = status.notificationFeedId {
                let destination = AlertDestination(connectionID: connectionID, feedID: feedID,
                    sequences: grouped ? page.alerts.map(\.sequence) : [message.sequence])
                content.userInfo["destination"] = try JSONEncoder().encode(destination).base64EncodedString()
            }
            content.sound = .default
            content.threadIdentifier = namespace
            let request = UNNotificationRequest(identifier: "\(namespace).\(message.sequence)", content: content, trigger: nil)
            try await center.add(request)
        }
        defaults.set(page.nextCursor, forKey: cursorKey(namespace))
        lastError = nil
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        Task { @MainActor in
            if self.enabled && self.companionEnabled && NSApp.isActive,
               let notice = self.notice(from: notification) {
                self.companion.show(notice)
                completionHandler([.list, .sound])
            } else { completionHandler([.banner, .list, .sound]) }
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            defer { completionHandler() }
            guard response.actionIdentifier == UNNotificationDefaultActionIdentifier,
                  let notice = self.notice(from: response.notification), let destination = notice.destination else { return }
            NSApp.activate(ignoringOtherApps: true)
            if self.companionEnabled { self.companion.show(notice) }
            else { self.companion.review?(destination) }
        }
    }

    private func notice(from notification: UNNotification) -> CompanionNotice? {
        let content = notification.request.content
        guard let encoded = content.userInfo["destination"] as? String,
              let data = Data(base64Encoded: encoded),
              let destination = try? JSONDecoder().decode(AlertDestination.self, from: data), destination.valid else { return nil }
        return CompanionNotice(id: notification.request.identifier, heading: content.title, detail: content.body,
                               account: content.subtitle, destination: destination)
    }
}
