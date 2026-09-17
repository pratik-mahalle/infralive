import Foundation
import Testing
@testable import CostBar

struct CloudTests {
    @Test @MainActor func cloudHealthPreventsAccidentalLocalWorkerEvenWhenCloudIsLate() async throws {
        let url = try #require(Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures"))
        var json = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        json["monitoring"] = ["mode": "cloud", "healthy": false, "checked_at": NSNull(), "message": "No recent heartbeat", "region": "us-east-1", "function_name": "cloudpulse-monitor"]
        let status = try AgentStatus.decode(JSONSerialization.data(withJSONObject: json))
        let model = AgentModel(start: false, fixture: status)
        #expect(model.usesCloudMonitoring)
        #expect(!model.isMonitoring)
        await model.startWorker()
        #expect(!model.ownsWorker)
        #expect(model.error == nil)
    }

    @Test func legacyTeamSpendingDoesNotPreventLoadingServiceCosts() throws {
        let url = try #require(Bundle.module.url(forResource: "demo-status", withExtension: "json", subdirectory: "Fixtures"))
        var json = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        var snapshot = try #require(json["snapshot"] as? [String: Any])
        snapshot["team_spending"] = ["legacy": "ignored"]
        json["snapshot"] = snapshot
        let status = try AgentStatus.decode(JSONSerialization.data(withJSONObject: json))
        #expect(status.snapshot?.analysis.topServices.isEmpty == false)
    }
}
