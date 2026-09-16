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

    @Test func missingTagAttributionRemainsExplicit() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let data = Data("""
        {"currency":"USD","total":"121.21","basis":"Before credits and refunds","dimensions":[
          {"id":"project","tag_key":"Project","state":"not_active","message":"Activate the billing tag",
           "groups":[{"id":"","name":"Unassigned","unassigned":true,"amount":"121.21"}]}]}
        """.utf8)
        let spending = try decoder.decode(TeamSpending.self, from: data)
        #expect(spending.dimensions.first?.state == "not_active")
        #expect(spending.dimensions.first?.groups.first?.amount == spending.total)
        #expect(spending.dimensions.first?.groups.first?.unassigned == true)
    }
}
