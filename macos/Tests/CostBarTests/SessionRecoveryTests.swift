import Foundation
import Testing
@testable import CostBar

private actor RecoveryBridge: AgentExecuting {
    let status: Data
    let failLogin: Bool
    private(set) var commands: [[String]] = []
    init(status: Data, failLogin: Bool = false) { self.status = status; self.failLogin = failLogin }
    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval) throws -> Data {
        commands.append(command)
        if command == ["login"] {
            if failLogin { throw BridgeError.message("SSO sign-in failed. Try again.") }
            return Data("{\"signed_in\":true}".utf8)
        }
        return status
    }
}

struct SessionRecoveryTests {
    private func cloudFixture() throws -> Data {
        let url = try #require(Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures"))
        var json = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        json["demo"] = false
        json["monitoring"] = ["mode": "cloud", "healthy": true, "checked_at": NSNull(), "message": "Healthy", "region": "us-east-1", "function_name": "cloudpulse-monitor"]
        return try JSONSerialization.data(withJSONObject: json)
    }

    @Test func expiredTokenTracebackBecomesShortSignInMessage() {
        let failure = BridgeError.processFailure("WARNING failed refresh\nTraceback\nFile /private/example.py\nbotocore.exceptions.TokenRetrievalError: expired\nAWS operation failed (TokenRetrievalError).")
        #expect(failure.requiresSignIn)
        #expect(!failure.localizedDescription.contains("Traceback"))
        #expect(!failure.localizedDescription.contains("/private/"))
        #expect(BridgeError.processFailure("AWS sign-in required: Session expired.").requiresSignIn)
        #expect(!BridgeError.processFailure("AWS operation failed (AccessDenied).").requiresSignIn)
        #expect(BridgeError.processFailure("Traceback\nError: Missing configuration").localizedDescription == "Error: Missing configuration")
    }

    @Test @MainActor func reconnectRetainsDataPausesPollingAndRecoversCloudConnection() async throws {
        let data = try cloudFixture()
        let fixture = try AgentStatus.decode(data)
        let bridge = RecoveryBridge(status: data)
        let model = AgentModel(start: false, fixture: fixture, bridge: bridge)
        let settings = model.settings
        model.recordFailure(BridgeError.authenticationRequired)
        #expect(model.needsSignIn)
        #expect(!model.isMonitoring)
        #expect(model.usesCloudMonitoring)
        #expect(model.status?.snapshot?.analysis.displayedSpend == fixture.snapshot?.analysis.displayedSpend)
        await model.load()
        #expect(await bridge.commands.isEmpty)
        await model.reconnect()
        #expect(!model.needsSignIn)
        #expect(model.isMonitoring)
        #expect(model.error == nil)
        #expect(model.settings == settings)
        let commands = await bridge.commands
        #expect(commands.prefix(2).elementsEqual([["login"], ["status"]]))
        #expect(!commands.contains(["sync"]))
        #expect(!commands.contains(["run"]))
    }

    @Test @MainActor func cancelledLoginKeepsCachedDataAndRetryAvailable() async throws {
        let data = try cloudFixture()
        let fixture = try AgentStatus.decode(data)
        let bridge = RecoveryBridge(status: data, failLogin: true)
        let model = AgentModel(start: false, fixture: fixture, bridge: bridge)
        model.recordFailure(BridgeError.authenticationRequired)
        await model.reconnect()
        #expect(model.needsSignIn)
        #expect(!model.busy)
        #expect(model.error == "SSO sign-in failed. Try again.")
        #expect(model.status?.snapshot?.analysis.displayedSpend == fixture.snapshot?.analysis.displayedSpend)
        #expect(await bridge.commands == [["login"]])
    }
}
