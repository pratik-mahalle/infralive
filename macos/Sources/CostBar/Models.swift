import Foundation

struct AgentStatus: Decodable {
    let schemaVersion: Int
    let demo: Bool
    let snapshot: Snapshot?
    let dailyTotals: [DailyTotal]
    let events: [ResourceEvent]
    let allEvents: [ResourceEvent]?
    let activity: ActivityStatus?
    let notifications: DeliveryStatus
    let worker: WorkerStatus
    let paths: AgentPaths
    let notificationCursor: Int?
    let notificationFeedId: String?
    let inboxSummary: InboxCounts?
    let monitoring: CloudMonitoring?

    static func decode(_ data: Data) throws -> AgentStatus {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(AgentStatus.self, from: data)
        guard value.schemaVersion == 1 else { throw BridgeError.message("Update Cloudwake to read this agent version.") }
        return value
    }
}

struct Snapshot: Decodable {
    let accountId: String
    let collectedAt: String
    let demo: Bool
    let analysis: Spending
    let forecast: Forecast?
    let recommendations: [Recommendation]
    let warnings: [String]
    let idleAlerts: [IdleAlert]?
    let savingsStatus: SavingsStatus?
    let reviewLeads: [ReviewLead]?
    let unusedResources: [UnusedResource]?
    let unusedMonitoring: UnusedMonitoring?

    var collectedDate: Date? { parseTimestamp(collectedAt) }
    var isStale: Bool { collectedDate.map { Date().timeIntervalSince($0) > 8 * 3600 } ?? true }
}

struct CloudMonitoring: Decodable {
    let mode: String
    let healthy: Bool
    let checkedAt: String?
    let message: String
    let region: String
    let functionName: String
}

struct SavingsStatus: Decodable {
    let state: String
    let message: String
}

struct UnusedMonitoring: Decodable {
    let thresholdDays: Int
    let regions: [String]
    let enabled: Bool
    let warnings: [String]
}

struct UnusedResource: Decodable, Identifiable {
    let id: String
    let resourceId: String
    let region: String
    let signal: String
    let observedDays: Int
    let thresholdDays: Int
    let ready: Bool
    let creator: String?
    let creationTime: String?
    let monthlySavings: String?
}

struct ReviewLead: Decodable, Identifiable {
    let id: String
    let title: String
    let detail: String
    let service: String
    let periodSpend: String
    let currency: String
    let source: String
}

struct ActivityRegion: Decodable {
    let region: String
    let backfillPending: Bool
}

struct ActivityStatus: Decodable {
    let mode: String
    let regions: [ActivityRegion]
    let warnings: [String]
    let checkedAt: String?
}

struct EnrollmentResponse: Decodable {
    struct Result: Decodable {
        let service: String
        let enabled: Bool
        let message: String
    }
    let results: [Result]
}

struct Spending: Decodable {
    let monthToDate: String
    let spendBeforeCredits: String?
    let credits: String?
    let refunds: String?
    var displayedSpend: String { spendBeforeCredits ?? monthToDate }
    let currency: String
    let costMetric: String
    let billingProvisional: Bool
    let billingThrough: String?
    let analyzedDay: String
    let anomalyCoverage: String
    let topServices: [ServiceCost]
    let anomalies: [CostAnomaly]
}

struct Forecast: Decodable {
    let monthTotal: String
    let method: String
}

struct ServiceCost: Decodable, Identifiable {
    let service: String
    let amount: String
    var id: String { service }
    var value: Double { Double(amount) ?? 0 }
    var shortName: String {
        service.replacingOccurrences(of: "AmazonCloudWatch", with: "CloudWatch")
            .replacingOccurrences(of: "Amazon ", with: "").replacingOccurrences(of: "AWS ", with: "")
    }
}

struct CostAnomaly: Decodable, Identifiable {
    let id: String
    let day: String
    let service: String
    let region: String
    let actual: String
    let baseline: String
    let increase: String
    let percent: String?
    let currency: String
}

struct Recommendation: Decodable, Identifiable {
    let id: String
    let resourceId: String
    let region: String
    let action: String
    let monthlySavings: String
    let currency: String
    let effort: String
    let source: String
    let restartNeeded: BoolOrText
}

enum BoolOrText: Decodable {
    case boolean(Bool)
    case text(String)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(Bool.self) { self = .boolean(value) }
        else { self = .text(try container.decode(String.self)) }
    }

    var label: String {
        switch self {
        case .boolean(true): return "Restart required"
        case .boolean(false): return "No restart indicated"
        case .text: return "Restart impact unknown"
        }
    }
}

struct DailyTotal: Decodable, Identifiable {
    let day: String
    let amount: String
    var id: String { day }
    var value: Double { Double(amount) ?? 0 }
}

struct ResourceEvent: Decodable, Identifiable {
    let id: String
    let time: String
    let region: String
    let action: String
    let service: String?
    let resourceIds: [String]
    let actor: String
    let owner: String
    let status: String
    let estimate: CostEstimate?

    var title: String {
        switch action {
        case "RunInstances": return "EC2 instance requested"
        case "CreateVolume": return "EBS volume requested"
        case "CreateNatGateway": return "NAT gateway requested"
        case "CreateDBInstance", "CreateDBCluster": return "RDS database requested"
        case "CreateFunction", "CreateFunction20150331": return "Lambda function requested"
        default: return "\(service?.uppercased() ?? "AWS") · \(action)"
        }
    }
    var symbol: String {
        switch action {
        case "RunInstances": return "server.rack"
        case "CreateVolume": return "externaldrive"
        case "CreateNatGateway": return "network"
        case "CreateDBInstance", "CreateDBCluster": return "cylinder.split.1x2"
        case "CreateFunction", "CreateFunction20150331": return "function"
        default: return "shippingbox"
        }
    }
}

struct CostEstimate: Decodable { let monthly: String; let assumptions: String }
struct DeliveryStatus: Decodable {
    let pending: Int
    let failed: Int
    let sent: Int
    let previewed: Int
    let delivery: String
}
struct WorkerStatus: Decodable { let running: Bool; let pid: Int? }
struct AgentPaths: Decodable { let database: String; let emailPreviews: String }

struct IdleAlert: Decodable, Identifiable {
    let id: String
    let resourceId: String
    let region: String
    let action: String
    let monthlySavings: String
    let currency: String
    let evidenceTimestamp: String
}

func parseTimestamp(_ raw: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = formatter.date(from: raw) { return date }
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.date(from: raw)
}

func currency(_ raw: String, code: String = "USD", compact: Bool = false) -> String {
    guard let value = Decimal(string: raw), !value.isNaN else { return "Unavailable" }
    let formatter = NumberFormatter()
    formatter.numberStyle = .currency
    formatter.currencyCode = code
    formatter.maximumFractionDigits = compact ? 0 : 2
    formatter.minimumFractionDigits = compact ? 0 : 2
    return formatter.string(from: NSDecimalNumber(decimal: value)) ?? "\(code) \(raw)"
}
