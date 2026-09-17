import Foundation
import Testing
@testable import CostBar

private actor CompanionBridge: AgentExecuting {
    let status: Data
    private(set) var commands: [[String]] = []
    init(status: Data) { self.status = status }
    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval) throws -> Data {
        commands.append(command)
        return status
    }
}

struct CompanionTests {
    private func fixture() throws -> Data {
        let url = try #require(Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures"))
        var value = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        value["notification_feed_id"] = "feed-a"
        return try JSONSerialization.data(withJSONObject: value)
    }

    @Test @MainActor func snoozeRejectsOtherAccountsAndReplacedFeedsWithoutMutations() async throws {
        let data = try fixture()
        let bridge = CompanionBridge(status: data)
        let model = AgentModel(start: true, fixture: try AgentStatus.decode(data), bridge: bridge)
        model.shutdown()
        model.connectionID = "account-a"
        for target in [
            AlertDestination(connectionID: "account-b", feedID: "feed-a", sequences: [1]),
            AlertDestination(connectionID: "account-a", feedID: "old-feed", sequences: [1]),
            AlertDestination(connectionID: "account-a", feedID: "feed-a", sequences: [-1]),
            AlertDestination(connectionID: "account-a", feedID: "feed-a", sequences: [])
        ] {
            await #expect(throws: (any Error).self) { try await model.snoozeNotification(target) }
        }
        #expect(await bridge.commands.isEmpty)
    }

    @Test @MainActor func snoozeUpdatesEveryGroupedAlertInItsOriginalFeedForOneHour() async throws {
        let data = try fixture()
        let bridge = CompanionBridge(status: data)
        let model = AgentModel(start: true, fixture: try AgentStatus.decode(data), bridge: bridge)
        model.shutdown()
        model.connectionID = "account-a"
        let destination = AlertDestination(connectionID: "account-a", feedID: "feed-a", sequences: [9, 8, 9])
        try await model.snoozeNotification(destination)
        let commands = await bridge.commands
        #expect(commands == [
            ["inbox", "update", "--sequence", "8", "--feed-id", "feed-a", "--action", "snooze", "--hours", "1"],
            ["inbox", "update", "--sequence", "9", "--feed-id", "feed-a", "--action", "snooze", "--hours", "1"],
            ["status"]
        ])
        #expect(!model.busy)
    }

    @Test @MainActor func previewsNeverSnoozeRealAlerts() async throws {
        let data = try fixture()
        let bridge = CompanionBridge(status: data)
        let model = AgentModel(start: false, fixture: try AgentStatus.decode(data), bridge: bridge)
        model.connectionID = "account-a"
        await #expect(throws: (any Error).self) {
            try await model.snoozeNotification(AlertDestination(connectionID: "account-a", feedID: "feed-a", sequences: [1]))
        }
        #expect(await bridge.commands.isEmpty)
    }
}
