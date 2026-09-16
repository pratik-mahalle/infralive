import Foundation
import Testing
@testable import CostBar

struct CostBarTests {
    @Test func creditsDoNotHideSpendingInTheMenu() throws {
        let data = Data("""
        {"month_to_date":"0.00","spend_before_credits":"121.21","credits":"-121.21","refunds":"0.00",
         "currency":"USD","cost_metric":"UnblendedCost","billing_provisional":true,
         "billing_through":"2026-09-15","analyzed_day":"2026-09-14","anomaly_coverage":"available",
         "top_services":[],"anomalies":[]}
        """.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let spending = try decoder.decode(Spending.self, from: data)
        #expect(spending.displayedSpend == "121.21")
        #expect(spending.monthToDate == "0.00")
        #expect(spending.credits == "-121.21")
    }

    @Test func guidedSetupDoesNotRequireConfigOrInheritDemoMode() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("costbar-setup-\(UUID())")
        let source = root.appendingPathComponent("src/aws_cost_agent")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data().write(to: source.appendingPathComponent("cli.py"))
        let settings = AgentSettings(projectPath: root.path, pythonPath: "/usr/bin/true", configPath: "missing.toml", demo: false)
        let process = try settings.makeProcess(["setup", "profiles"])
        #expect(process.arguments == ["-m", "aws_cost_agent", "setup", "profiles"])
        #expect(throws: (any Error).self) { try settings.makeProcess(["sync"]) }
        var demo = settings
        demo.demo = true
        #expect(try demo.makeProcess(["setup", "profiles"]).arguments == process.arguments)
    }

    @Test func connectionReviewUsesBackendAccountAndCostsReadiness() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let data = Data("""
        {"account_id":"123456789012","principal":"role/test","profile":"test","region":"us-east-1",
         "checks":[{"id":"costs","title":"Spending data","ready":false,"detail":"Permission needed"}]}
        """.utf8)
        let result = try decoder.decode(ConnectionReview.self, from: data)
        #expect(result.accountId == "123456789012")
        #expect(!result.costsReady)
    }

    @Test func notificationBurstsAreGroupedAndDemoIsExplicit() {
        let alerts = (1...5).map { DesktopAlert(sequence: $0, kind: $0 == 5 ? "idle" : "event", title: "New resource", body: "Evidence") }
        let messages = NotificationPlan.messages(alerts, demo: true)
        #expect(messages.count == 1)
        #expect(messages[0].sequence == 5)
        #expect(messages[0].title == "[Demo] 5 AWS alerts")
        #expect(messages[0].body.contains("4 resource changes"))
        #expect(messages[0].body.contains("1 idle-resource"))
    }

    @Test func individualAlertIsKeptAndCursorScopesDoNotMix() {
        let alert = DesktopAlert(sequence: 42, kind: "idle", title: "Idle resource", body: "Estimated $40/month avoidable cost")
        let messages = NotificationPlan.messages([alert], demo: false)
        #expect(messages[0].title == "Idle resource")
        #expect(messages[0].body.contains("$40/month"))
        #expect(NotificationPlan.messages([], demo: true).isEmpty)
        let live = NotificationPlan.key(database: "database", demo: false, account: "feed1")
        #expect(live != NotificationPlan.key(database: "database", demo: true, account: "feed1"))
        #expect(live != NotificationPlan.key(database: "database", demo: false, account: "feed2"))
    }

    @Test func nativeFeedDecodesTheBackendCursor() throws {
        let data = Data("""
        {"alerts":[{"sequence":14,"kind":"event","title":"New S3 bucket","body":"Evidence"}],"next_cursor":14}
        """.utf8)
        let page = try AlertPage.decode(data)
        #expect(page.nextCursor == 14)
        #expect(page.alerts[0].kind == "event")
    }

    @Test func pythonStatusContract() throws {
        let url = try #require(Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures"))
        let status = try AgentStatus.decode(Data(contentsOf: url))
        #expect(status.demo)
        #expect(status.snapshot?.accountId == "123456789012")
        #expect(status.snapshot?.analysis.monthToDate == "4035.00")
        #expect(status.snapshot?.analysis.anomalies.count == 1)
        #expect(status.snapshot?.idleAlerts?.first?.monthlySavings == "40.00")
        #expect(status.notificationCursor == 3)
        #expect(status.notificationFeedId == "fixture-demo-feed")
        #expect(status.events.first?.owner == "Payments (demo)")
        #expect(status.dailyTotals.count == 14)
    }

    @Test func unsupportedSchemaIsActionable() throws {
        let url = try #require(Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures"))
        let data = try Data(contentsOf: url)
        var json = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
        json["schema_version"] = 2
        #expect(throws: (any Error).self) { try AgentStatus.decode(JSONSerialization.data(withJSONObject: json)) }
    }

    @Test func unknownRestartRequirementDoesNotClaimSafe() throws {
        let value = try JSONDecoder().decode(BoolOrText.self, from: Data("\"Unknown\"".utf8))
        #expect(value.label == "Restart impact unknown")
    }

    @Test func timestampWithAndWithoutFraction() {
        #expect(parseTimestamp("2026-09-16T15:00:00.123456+00:00") != nil)
        #expect(parseTimestamp("2026-09-16T15:00:00Z") != nil)
        #expect(parseTimestamp("invalid") == nil)
    }

    @Test func questionAndPathsArePassedWithoutShellEvaluation() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("cost bar test \(UUID())")
        let source = root.appendingPathComponent("src/aws_cost_agent")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        FileManager.default.createFile(atPath: source.appendingPathComponent("cli.py").path, contents: Data())
        let settings = AgentSettings(projectPath: root.path, pythonPath: "/usr/bin/true", configPath: "", demo: true)
        let question = "why $(touch unwanted) `something` ; echo test?"
        let process = try settings.makeProcess(["ask", question])
        #expect(process.executableURL?.path == "/usr/bin/true")
        #expect(process.arguments?.last == question)
        #expect(process.currentDirectoryURL?.path == root.path)
    }

    @Test func bridgeHandlesLargeOutputAndFailures() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("costbar-bridge-\(UUID())")
        let source = root.appendingPathComponent("src/aws_cost_agent")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data().write(to: source.appendingPathComponent("cli.py"))
        try Data().write(to: source.appendingPathComponent("__init__.py"))
        let script = """
        import sys, time
        if sys.argv[-1] == 'fail':
            sys.stderr.write('Actionable test error')
            sys.exit(2)
        if sys.argv[-1] == 'slow':
            time.sleep(10)
        print('x' * 100000)
        """
        try script.write(to: source.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)
        let settings = AgentSettings(projectPath: root.path, pythonPath: "/usr/bin/python3", configPath: "", demo: true)
        let bridge = AgentBridge()
        let data = try await bridge.execute(settings: settings, command: ["status"])
        #expect(data.count == 100001)
        await #expect(throws: (any Error).self) {
            try await bridge.execute(settings: settings, command: ["fail"])
        }
        await #expect(throws: (any Error).self) {
            try await bridge.execute(settings: settings, command: ["slow"], timeout: 0.2)
        }
    }
}
