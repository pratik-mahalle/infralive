import Foundation
import Testing
@testable import CostBar

private actor AccountBridge: AgentExecuting {
    private(set) var commands: [(String, [String])] = []
    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval) throws -> Data {
        commands.append((settings.configPath, command))
        if command.first == "alerts" { return Data("{\"alerts\":[],\"next_cursor\":0}".utf8) }
        let url = Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures")!
        var value = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        let account = URL(fileURLWithPath: settings.configPath).deletingPathExtension().lastPathComponent
        value["demo"] = settings.demo
        var snapshot = value["snapshot"] as! [String: Any]
        snapshot["account_id"] = account
        value["snapshot"] = snapshot
        value["notification_feed_id"] = account
        var paths = value["paths"] as! [String: Any]
        paths["database"] = settings.configPath + ".sqlite3"
        value["paths"] = paths
        return try JSONSerialization.data(withJSONObject: value)
    }
}

@MainActor
struct AccountWorkspaceTests {
    private func environment() throws -> (URL, UserDefaults, String) {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("accounts-\(UUID())")
        try FileManager.default.createDirectory(at: root.appendingPathComponent("src/aws_cost_agent"), withIntermediateDirectories: true)
        try Data().write(to: root.appendingPathComponent("src/aws_cost_agent/cli.py"))
        let worker = root.appendingPathComponent("worker")
        try Data("#!/bin/sh\nexec /bin/sleep 60\n".utf8).write(to: worker)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: worker.path)
        let suite = "CloudwakeTests.\(UUID())"
        return (root, UserDefaults(suiteName: suite)!, suite)
    }
    private func settings(_ root: URL, account: String, demo: Bool = false) throws -> AgentSettings {
        let config = root.appendingPathComponent(account + ".toml")
        try Data().write(to: config)
        return AgentSettings(projectPath: root.path, pythonPath: root.appendingPathComponent("worker").path,
                             configPath: config.path, demo: demo)
    }

    @Test func migratesExistingConnectionAndPersistsSelectionAndNames() async throws {
        let (root, defaults, suite) = try environment()
        defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        let first = try settings(root, account: "111111111111")
        defaults.set(try JSONEncoder().encode(first), forKey: "CostBar.settings.v1")
        let workspace = AccountWorkspace(defaults: defaults, start: false)
        defer { workspace.shutdown() }
        let original = workspace.selectedID
        #expect(workspace.selectedModel.settings == first)
        let second = try await workspace.connect(settings: settings(root, account: "222222222222"), accountID: "222222222222", name: "Staging")
        #expect(workspace.realAccountCount == 2)
        #expect(workspace.selectedID == second)
        workspace.select(original)
        workspace.rename(original, name: "Production")
        let restored = AccountWorkspace(defaults: defaults, start: false)
        defer { restored.shutdown() }
        #expect(restored.selectedID == original)
        #expect(restored.accounts.first?.title == "Production")
        #expect(restored.accounts.last?.monitoringRequested == true)
        #expect(restored.selectedModel.settings == first)
        let legacy = try #require(defaults.data(forKey: "CostBar.settings.v1"))
        #expect(try JSONDecoder().decode(AgentSettings.self, from: legacy) == first)
    }

    @Test func switchingKeepsWorkersRunningAndExpiredSessionDoesNotBlockOtherAccount() async throws {
        let (root, defaults, suite) = try environment()
        defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        let bridge = AccountBridge()
        let workspace = AccountWorkspace(defaults: defaults, start: false,
                                         initialSettings: try settings(root, account: "demo", demo: true), makeBridge: { bridge })
        defer { workspace.shutdown() }
        let first = try await workspace.connect(settings: settings(root, account: "111111111111"), accountID: "111111111111", name: "Production")
        let second = try await workspace.connect(settings: settings(root, account: "222222222222"), accountID: "222222222222", name: "Staging")
        let production = try #require(workspace.model(for: first))
        let staging = try #require(workspace.model(for: second))
        await production.load()
        await staging.load()
        await production.startWorker()
        await staging.startWorker()
        #expect(production.ownsWorker && staging.ownsWorker)
        workspace.select(first)
        workspace.select(second)
        #expect(production.ownsWorker && staging.ownsWorker)
        #expect(workspace.selectedModel === staging)
        #expect(production.notifier === staging.notifier)
        let reconnected = try await workspace.connect(settings: production.settings, accountID: "111111111111", name: "Production")
        #expect(reconnected == first)
        #expect(workspace.realAccountCount == 2)
        #expect(production.ownsWorker && staging.ownsWorker)
        #expect(production.monitoringRequested)
        production.recordFailure(BridgeError.authenticationRequired)
        await staging.refresh()
        #expect(production.needsSignIn)
        #expect(!staging.needsSignIn)
        #expect(staging.status?.snapshot?.accountId == "222222222222")
        #expect(production.status?.snapshot?.accountId == "111111111111")
        #expect(production.accountLabel == "Production · 111111111111")
        #expect(production.notifier.namespace(production.status!) != staging.notifier.namespace(staging.status!))
        production.stopWorker()
        #expect(!production.monitoringRequested)
        #expect(staging.monitoringRequested && staging.ownsWorker)
        workspace.remove(first)
        #expect(workspace.model(for: first) == nil)
        #expect(staging.ownsWorker)
        #expect(FileManager.default.fileExists(atPath: production.settings.configPath))
    }

    @Test func reconnectDeduplicatesAccountAndRemovalKeepsOtherData() async throws {
        let (root, defaults, suite) = try environment()
        defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        let original = try settings(root, account: "111111111111")
        let workspace = AccountWorkspace(defaults: defaults, start: false, initialSettings: original)
        defer { workspace.shutdown() }
        let id = workspace.selectedID
        let reconnected = try await workspace.connect(settings: original, accountID: "111111111111", name: "Production")
        #expect(reconnected == id)
        #expect(workspace.realAccountCount == 1)
        #expect(workspace.accounts.first?.title == "Production")
        workspace.remove(id)
        #expect(workspace.selectedModel.settings.demo)
        #expect(workspace.realAccountCount == 0)
        #expect(FileManager.default.fileExists(atPath: original.configPath))
        let restored = AccountWorkspace(defaults: defaults, start: false)
        defer { restored.shutdown() }
        #expect(restored.selectedModel.settings.demo)
    }

    @Test func relaunchResumesEveryEnabledAccountAndKeepsPausedAccountPaused() async throws {
        let (root, defaults, suite) = try environment()
        defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        let bridge = AccountBridge()
        let workspace = AccountWorkspace(defaults: defaults, start: false,
                                         initialSettings: try settings(root, account: "demo", demo: true), makeBridge: { bridge })
        let first = try await workspace.connect(settings: settings(root, account: "111111111111"), accountID: "111111111111", name: "Production")
        let second = try await workspace.connect(settings: settings(root, account: "222222222222"), accountID: "222222222222", name: "Staging")
        let paused = try await workspace.connect(settings: settings(root, account: "333333333333"), accountID: "333333333333", name: "Paused")
        workspace.model(for: paused)?.stopWorker()
        workspace.shutdown()
        let restored = AccountWorkspace(defaults: defaults, start: true, makeBridge: { bridge })
        defer { restored.shutdown() }
        for _ in 0..<100 {
            if restored.model(for: first)?.ownsWorker == true && restored.model(for: second)?.ownsWorker == true { break }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        #expect(restored.model(for: first)?.ownsWorker == true)
        #expect(restored.model(for: second)?.ownsWorker == true)
        #expect(restored.model(for: paused)?.ownsWorker == false)
        #expect(restored.selectedID == paused)
    }

    @Test func unreadableRegistryIsNotOverwritten() throws {
        let (root, defaults, suite) = try environment()
        defer { defaults.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        let broken = Data("invalid".utf8)
        defaults.set(broken, forKey: "Cloudwake.accounts.v1")
        let workspace = AccountWorkspace(defaults: defaults, start: false, initialSettings: try settings(root, account: "demo", demo: true))
        defer { workspace.shutdown() }
        #expect(workspace.storageError != nil)
        #expect(defaults.data(forKey: "Cloudwake.accounts.v1") == broken)
    }
}
