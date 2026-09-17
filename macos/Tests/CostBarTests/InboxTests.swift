import Foundation
import Testing
@testable import CostBar

struct InboxTests {
    private func fixture() throws -> InboxPage {
        let url = try #require(Bundle.module.url(forResource: "inbox", withExtension: "json", subdirectory: "Fixtures"))
        return try InboxPage.decode(Data(contentsOf: url))
    }

    @Test func backendInboxContractPreservesEvidenceAndAccountScope() throws {
        let page = try fixture()
        #expect(page.feedId == "fixture-inbox")
        #expect(page.filter == .open)
        #expect(page.counts.unread == 3)
        #expect(page.nextBefore == nil)
        let first = try #require(page.alerts.first)
        #expect(first.feedId == page.feedId)
        #expect(first.unread && first.state == .open)
        #expect(first.body.contains("assumed-role/Engineering/alex"))
        #expect(first.body.contains("Potential saving: not yet measured"))
        #expect(first.summary == "Resource: vol-demo-staging")
        #expect(first.snoozedUntil == nil)
        #expect(parseTimestamp(first.createdAt) != nil)
    }

    @Test @MainActor func renderingInboxCannotMutateOrLoadTheRealAccount() async throws {
        let page = try fixture()
        let model = AgentModel(start: false, inboxFixture: page)
        #expect(model.isPreview)
        let alert = try #require(page.alerts.first)
        #expect(await model.updateInbox(alert, action: "review") == false)
        await model.loadInbox(filter: .reviewed)
        #expect(model.inboxFilter == .open)
        #expect(model.inboxPage?.counts.unread == 3)
    }
}
