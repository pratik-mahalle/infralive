import CryptoKit
import Foundation
import UserNotifications
import Combine

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
    private let defaults = UserDefaults.standard
    // Do not instantiate Notification Center in unsigned test / render executables.
    private var center: UNUserNotificationCenter { UNUserNotificationCenter.current() }

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

    func publish(_ page: AlertPage, status: AgentStatus, accountLabel: String? = nil) async throws {
        guard enabled, !page.alerts.isEmpty else { return }
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            await checkPermission()
            throw BridgeError.message("Allow Cloudwake notifications in macOS System Settings.")
        }
        let namespace = namespace(status)
        for message in NotificationPlan.messages(page.alerts, demo: status.demo) {
            let content = UNMutableNotificationContent()
            content.title = message.title
            content.subtitle = accountLabel ?? status.snapshot.map { "AWS account " + $0.accountId } ?? ""
            content.body = message.body
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
        completionHandler([.banner, .list, .sound])
    }
}
