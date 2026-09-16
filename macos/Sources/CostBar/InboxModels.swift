import Foundation

enum InboxFilter: String, Decodable, CaseIterable {
    case open, snoozed, reviewed
    var title: String { rawValue.capitalized }
}

struct InboxCounts: Decodable {
    let total: Int
    let open: Int
    let snoozed: Int
    let reviewed: Int
    let unread: Int
}

struct InboxAlert: Decodable, Identifiable {
    let feedId: String
    let sequence: Int
    let alertId: String
    let kind: String
    let title: String
    let body: String
    let createdAt: String
    let readAt: String?
    let reviewedAt: String?
    let snoozedUntil: String?
    let state: InboxFilter
    let unread: Bool
    var id: Int { sequence }
    var kindLabel: String {
        switch kind {
        case "event": return "Resource"
        case "spend": return "Spending"
        case "budget": return "Budget"
        case "idle": return "Unused resource"
        default: return "Alert"
        }
    }
    var summary: String? {
        body.components(separatedBy: .newlines).first {
            $0.hasPrefix("Resource:") || $0.hasPrefix("Resources:") || $0.hasPrefix("Forecast:")
        }
    }
}

struct InboxPage: Decodable {
    let feedId: String
    let filter: InboxFilter
    let alerts: [InboxAlert]
    let counts: InboxCounts
    let nextBefore: Int?

    static func decode(_ data: Data) throws -> InboxPage {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(InboxPage.self, from: data)
    }
}
