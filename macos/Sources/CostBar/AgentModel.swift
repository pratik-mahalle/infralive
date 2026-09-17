import AppKit
import Combine
import Foundation

@MainActor
final class AgentModel: ObservableObject {
    @Published private(set) var settings: AgentSettings
    @Published private(set) var status: AgentStatus?
    @Published private(set) var busy = false
    @Published private(set) var needsSignIn = false
    @Published var configuring = false
    @Published var error: String?
    @Published var notice: String?
    @Published private(set) var ownsWorker = false
    @Published private(set) var answer = ""
    @Published private(set) var asking = false
    @Published private(set) var inboxPage: InboxPage?
    @Published private(set) var inboxFilter: InboxFilter = .open
    @Published private(set) var inboxError: String?
    @Published private(set) var inboxCursors: [Int] = [0]
    let isPreview: Bool

    private let bridge: any AgentExecuting
    let notifier = DesktopNotifier()
    private var worker: Process?
    private var workerLog: FileHandle?
    private var timer: Task<Void, Never>?
    private var terminationSubscription: AnyCancellable?
    private let preferenceKey = "CostBar.settings.v1"

    init(start: Bool = true, fixture: AgentStatus? = nil, inboxFixture: InboxPage? = nil, bridge: any AgentExecuting = AgentBridge()) {
        self.bridge = bridge
        isPreview = !start
        inboxPage = inboxFixture
        if let inboxFixture { inboxFilter = inboxFixture.filter }
        if let data = UserDefaults.standard.data(forKey: preferenceKey),
           let saved = try? JSONDecoder().decode(AgentSettings.self, from: data) {
            settings = saved
            // Homebrew upgrades and moving the app must not retain old bundle paths.
            if saved.dataPath != nil && saved.projectPath.hasSuffix(".app/Contents/Resources/Agent"),
               AgentSettings.initial.dataPath != nil {
                settings.projectPath = AgentSettings.initial.projectPath
                settings.pythonPath = AgentSettings.initial.pythonPath
            }
        } else { settings = .initial }
        status = fixture
        if let fixture { settings.demo = fixture.demo }
        terminationSubscription = NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)
            .sink { [weak self] _ in self?.shutdown() }
        if start {
            timer = Task { [weak self] in
                await self?.notifier.checkPermission()
                await self?.load(initial: true)
                if CommandLine.arguments.contains("--resume-monitoring") {
                    await self?.startWorker()
                }
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 30_000_000_000)
                    guard !Task.isCancelled else { return }
                    await self?.load()
                }
            }
        }
    }

    var menuLabel: String {
        guard let snapshot = status?.snapshot else { return settings.demo ? "Demo" : "AWS" }
        return (settings.demo ? "Demo " : "") + currency(snapshot.analysis.displayedSpend,
                                                        code: snapshot.analysis.currency, compact: true)
    }
    var alertCount: Int { (status?.snapshot?.analysis.anomalies.count ?? 0) + (status?.snapshot?.idleAlerts?.count ?? 0) }
    var usesCloudMonitoring: Bool { status?.monitoring?.mode == "cloud" }
    var isMonitoring: Bool { !needsSignIn && (usesCloudMonitoring ? status?.monitoring?.healthy == true : ownsWorker || status?.worker.running == true) }

    func load(initial: Bool = false) async {
        guard !busy && !needsSignIn else { return }
        busy = true
        defer { busy = false }
        do {
            var data = try await bridge.execute(settings: settings, command: ["status"], timeout: 15)
            let saved = try AgentStatus.decode(data)
            if initial && settings.demo && saved.snapshot == nil {
                _ = try await bridge.execute(settings: settings, command: ["demo"])
                data = try await bridge.execute(settings: settings, command: ["status"], timeout: 15)
            }
            status = try AgentStatus.decode(data)
            error = nil
            if inboxPage != nil { await reloadInboxPage() }
            await checkDesktopAlerts()
        } catch { recordFailure(error) }
    }

    func recordFailure(_ failure: Error) {
        if (failure as? BridgeError)?.requiresSignIn == true {
            needsSignIn = true
            notice = nil
        }
        error = failure.localizedDescription
    }

    func reconnect() async {
        await retryConnection(signIn: true)
    }

    func retryConnection(signIn: Bool = false) async {
        guard !busy && !configuring && !settings.demo else { return }
        busy = true
        notice = signIn ? "Complete AWS sign-in in your browser…" : "Checking your AWS connection…"
        defer { busy = false }
        do {
            if signIn { _ = try await bridge.execute(settings: settings, command: ["login"], timeout: 200) }
            var latest = try AgentStatus.decode(await bridge.execute(settings: settings, command: ["status"], timeout: 30))
            if latest.monitoring?.mode != "cloud" {
                _ = try await bridge.execute(settings: settings, command: ["sync"], timeout: 300)
                latest = try AgentStatus.decode(await bridge.execute(settings: settings, command: ["status"]))
            }
            status = latest
            needsSignIn = false
            error = nil
            notice = "AWS reconnected. Your saved connection is unchanged."
            if inboxPage != nil { await reloadInboxPage() }
            await checkDesktopAlerts()
        } catch {
            notice = nil
            recordFailure(error)
        }
    }

    func refresh() async {
        guard !busy && !configuring else { return }
        busy = true
        error = nil
        notice = nil
        do {
            _ = try await bridge.execute(settings: settings, command: [settings.demo ? "demo" : "sync"], timeout: 300)
            if !settings.demo && !usesCloudMonitoring {
                _ = try await bridge.execute(settings: settings, command: ["history"], timeout: 240)
            }
            status = try AgentStatus.decode(await bridge.execute(settings: settings, command: ["status"]))
            needsSignIn = false
            await checkDesktopAlerts()
            notice = settings.demo ? "Demo refreshed. No AWS requests made." : "Latest available AWS billing collected."
        } catch { recordFailure(error) }
        busy = false
    }

    func refreshHistory() async {
        guard !busy && !settings.demo else { return }
        busy = true
        defer { busy = false }
        do {
            _ = try await bridge.execute(settings: settings, command: ["history"], timeout: 240)
            status = try AgentStatus.decode(await bridge.execute(settings: settings, command: ["status"]))
            error = nil
            needsSignIn = false
            await checkDesktopAlerts()
        } catch { recordFailure(error) }
    }

    func enableSavings() async {
        guard !busy && !settings.demo else { return }
        busy = true
        defer { busy = false }
        do {
            let data = try await bridge.execute(settings: settings, command: ["enable-savings"], timeout: 120)
            let response = try JSONDecoder().decode(EnrollmentResponse.self, from: data)
            let failures = response.results.filter { !$0.enabled }
            notice = failures.isEmpty ? "Savings analysis enabled. AWS needs time to generate recommendations." : failures.map { $0.service + ": " + $0.message }.joined(separator: " ")
            _ = try await bridge.execute(settings: settings, command: ["sync"], timeout: 180)
            status = try AgentStatus.decode(await bridge.execute(settings: settings, command: ["status"]))
            error = nil
            needsSignIn = false
        } catch { recordFailure(error) }
    }

    func save(_ updated: AgentSettings) async {
        guard !busy && !asking && !ownsWorker else {
            error = "Stop the worker and wait for the current task before changing accounts."
            return
        }
        do {
            _ = try updated.makeProcess(["status"])
            UserDefaults.standard.set(try JSONEncoder().encode(updated), forKey: preferenceKey)
            settings = updated
            needsSignIn = false
            status = nil
            inboxPage = nil
            inboxFilter = .open
            inboxCursors = [0]
            inboxError = nil
            answer = ""
            notice = nil
            await load(initial: true)
        } catch { recordFailure(error) }
    }

    private func checkDesktopAlerts() async {
        guard notifier.enabled, let status else { return }
        do {
            let after = notifier.cursor(for: status)
            // One page per poll bounds notification work; subsequent polls drain bursts.
            let data = try await bridge.execute(settings: settings, command: ["alerts", "--after", String(after)], timeout: 15)
            let page = try AlertPage.decode(data)
            try await notifier.publish(page, status: status)
        } catch {
            if (error as? BridgeError)?.requiresSignIn == true { recordFailure(error) }
            else { notice = "Mac notification delivery needs attention: " + error.localizedDescription }
        }
    }

    func loadInbox(filter: InboxFilter? = nil, direction: Int = 0) async {
        guard !busy, !isPreview else { return }
        busy = true
        defer { busy = false }
        if let filter {
            inboxFilter = filter
            inboxCursors = [0]
            inboxPage = nil
        } else if direction > 0, let cursor = inboxPage?.nextBefore {
            inboxCursors.append(cursor)
        } else if direction < 0, inboxCursors.count > 1 {
            inboxCursors.removeLast()
        }
        await reloadInboxPage()
    }

    private func reloadInboxPage() async {
        guard !isPreview else { return }
        do {
            let data = try await bridge.execute(settings: settings, command: ["inbox", "list", "--filter", inboxFilter.rawValue,
                "--before", String(inboxCursors.last ?? 0)], timeout: 15)
            inboxPage = try InboxPage.decode(data)
            inboxError = nil
        } catch {
            inboxPage = nil
            inboxError = error.localizedDescription
            if (error as? BridgeError)?.requiresSignIn == true { recordFailure(error) }
        }
    }

    @discardableResult
    func updateInbox(_ alert: InboxAlert, action: String, hours: Int = 24) async -> Bool {
        guard !busy, !isPreview, let page = inboxPage else { return false }
        guard alert.feedId == page.feedId, page.feedId == status?.notificationFeedId else {
            inboxError = "This alert belongs to another inbox. Refresh and try again."
            return false
        }
        busy = true
        defer { busy = false }
        do {
            _ = try await bridge.execute(settings: settings, command: ["inbox", "update", "--sequence", String(alert.sequence),
                "--feed-id", alert.feedId, "--action", action, "--hours", String(hours)], timeout: 15)
            status = try AgentStatus.decode(await bridge.execute(settings: settings, command: ["status"], timeout: 15))
            await reloadInboxPage()
            return true
        } catch {
            inboxError = error.localizedDescription
            if (error as? BridgeError)?.requiresSignIn == true { recordFailure(error) }
            return false
        }
    }

    func startWorker() async {
        guard !busy && !configuring && !needsSignIn && !isMonitoring && !usesCloudMonitoring else { return }
        error = nil
        do {
            let process = try settings.makeProcess(["run"])
            let directory = URL(fileURLWithPath: settings.workingDirectory).appendingPathComponent("data")
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let log = directory.appendingPathComponent(settings.demo ? "menubar-demo.log" : "menubar-worker.log")
            FileManager.default.createFile(atPath: log.path, contents: nil)
            let handle = try FileHandle(forWritingTo: log)
            process.standardOutput = handle
            process.standardError = handle
            process.terminationHandler = { [weak self] exited in
                Task { @MainActor in
                    guard let self, self.worker === exited else { return }
                    self.worker = nil
                    self.ownsWorker = false
                    try? self.workerLog?.close()
                    self.workerLog = nil
                    if exited.terminationStatus != 0 && exited.terminationReason == .exit {
                        let detail = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
                        self.recordFailure(BridgeError.processFailure(detail))
                    }
                    await self.load()
                }
            }
            try process.run()
            worker = process
            workerLog = handle
            ownsWorker = true
            notice = settings.demo ? "Demo worker started. Emails stay local." : "Monitoring started using your configured email delivery."
            await load()
        } catch { recordFailure(error) }
    }

    func stopWorker() {
        guard let worker, worker.isRunning else { return }
        worker.terminate()
        notice = "Stopping the worker…"
    }

    func shutdown() {
        timer?.cancel()
        if let worker, worker.isRunning { worker.terminate() }
    }

    func ask(_ question: String) async {
        guard !asking && !busy && !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        asking = true
        answer = ""
        defer { asking = false }
        do {
            let data = try await bridge.execute(settings: settings, command: ["ask", question], timeout: 180)
            answer = String(decoding: data, as: UTF8.self)
        } catch { answer = "Unable to investigate: " + error.localizedDescription }
    }

    func openReport() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let data = try await bridge.execute(settings: settings, command: ["report"])
            let directory = URL(fileURLWithPath: settings.workingDirectory).appendingPathComponent("data")
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let file = directory.appendingPathComponent(settings.demo ? "demo-report.txt" : "aws-report.txt")
            try data.write(to: file, options: .atomic)
            NSWorkspace.shared.open(file)
        } catch { recordFailure(error) }
    }

    func openPreviews() {
        guard let path = status?.paths.emailPreviews else { return }
        do {
            try FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
            NSWorkspace.shared.open(URL(fileURLWithPath: path))
        } catch { recordFailure(error) }
    }
}
