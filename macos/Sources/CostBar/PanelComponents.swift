import SwiftUI

struct PanelHeading: View {
    let title: String
    let detail: String
    var body: some View {
        HStack {
            Text(title).font(.system(size: 12, weight: .semibold))
            Spacer()
            Text(detail).font(.caption2).foregroundStyle(.secondary)
        }
    }
}

struct InlineNotice: View {
    let text: String
    let warning: Bool
    var body: some View {
        Label {
            Text(text).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: warning ? "exclamationmark.circle" : "clock")
                .foregroundStyle(warning ? Color.orange : Color.secondary)
        }.font(.caption).foregroundStyle(.secondary)
    }
}

struct QuietEmptyState: View {
    let title: String
    let detail: String
    let symbol: String
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            CloudMascot(size: 48, sleepy: true)
            VStack(alignment: .leading, spacing: 7) {
                Text(title).font(.system(size: 13, weight: .semibold, design: .rounded))
                Text(detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }.padding(.vertical, 16).frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ActivityRow: View {
    let event: ResourceEvent
    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 9) {
                DetailText(title: "Resources", value: event.resourceIds.joined(separator: "\n"))
                DetailText(title: "AWS identity", value: event.actor)
                if event.owner != "Unassigned" { DetailText(title: "Owner", value: event.owner) }
                DetailText(title: "API call", value: "\(event.action) · \(event.region)")
                Text(event.status).font(.caption).foregroundStyle(.secondary)
                if let estimate = event.estimate {
                    Text("~\(currency(estimate.monthly))/mo estimated compute").font(.caption)
                    Text(estimate.assumptions).font(.caption2).foregroundStyle(.secondary)
                }
            }.padding(.top, 4).padding(.bottom, 12)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: event.symbol).font(.system(size: 13)).foregroundStyle(.secondary)
                    .frame(width: 16).padding(.top, 2).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 5) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(event.compactTitle).font(.system(size: 12, weight: .medium)).lineLimit(1).help(event.title)
                        Spacer(minLength: 6)
                        if let time = parseTimestamp(event.time) {
                            Text(time.formatted(.dateTime.month(.abbreviated).day())).font(.system(size: 10)).foregroundStyle(.secondary)
                                .help(time.formatted(date: .complete, time: .standard))
                        }
                    }
                    Text(compactResource(event.primaryResource))
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                    HStack {
                        Text(compactIdentity(event.actor)).lineLimit(1).truncationMode(.middle)
                        Spacer(minLength: 6)
                        if let time = parseTimestamp(event.time) { Text(time.formatted(date: .omitted, time: .shortened)) }
                    }.font(.system(size: 10)).foregroundStyle(.secondary)
                }
            }
        }
    }
}

struct RecommendationRow: View {
    let recommendation: Recommendation
    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 8) {
                DetailText(title: "Resource", value: recommendation.resourceId)
                Text("\(recommendation.region) · \(recommendation.effort) effort · \(recommendation.restartNeeded.label)")
                    .font(.caption).foregroundStyle(.secondary)
                Text("\(recommendation.source). Review workload requirements before making a change.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(.vertical, 8)
        } label: {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    Text(recommendation.action).font(.system(size: 12, weight: .medium)).lineLimit(2)
                    Spacer()
                    Text("\(currency(recommendation.monthlySavings, code: recommendation.currency))/mo")
                        .font(.system(size: 12, weight: .medium)).monospacedDigit().fixedSize()
                }
                Text(compactResource(recommendation.resourceId))
                    .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
        }
    }
}

struct UnusedResourceRow: View {
    let resource: UnusedResource
    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 9) {
                DetailText(title: "Resource", value: resource.resourceId)
                DetailText(title: "Creator’s AWS identity", value: resource.creator ?? "Unavailable in collected CloudTrail history")
                if let created = resource.creationTime.flatMap(parseTimestamp) {
                    Text("Created \(created.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                }
                Text("\(resource.signal) · \(resource.region)").font(.caption).foregroundStyle(.secondary)
                Text(resource.monthlySavings.map { "AWS estimated saving: \(currency($0))/mo" } ?? "Savings not yet measured.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(.vertical, 8)
        } label: {
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text(compactResource(resource.resourceId)).font(.system(size: 11, design: .monospaced))
                        .lineLimit(1).truncationMode(.middle)
                    Spacer()
                    Text(resource.ready ? "\(resource.observedDays) days" : "Day \(resource.observedDays) of \(resource.thresholdDays)")
                        .font(.caption).foregroundStyle(resource.ready ? Color.orange : Color.secondary).fixedSize()
                }
                Text(resource.ready ? "Repeatedly flagged unused · Review with owner" : "Watching for continued inactivity")
                    .font(.caption).foregroundStyle(.secondary)
                if let creator = resource.creator {
                    Text(compactIdentity(creator)).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
            }
        }
    }
}

private struct DetailText: View {
    let title: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 10, weight: .medium)).foregroundStyle(.secondary)
            Text(value).font(.system(size: 11)).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private func compactResource(_ value: String) -> String {
    guard value.hasPrefix("arn:") else { return value }
    return value.split(separator: ":", maxSplits: 5).last.map(String.init) ?? value
}

private func compactIdentity(_ value: String) -> String {
    if let range = value.range(of: ":assumed-role/") { return "Role · " + value[range.upperBound...].replacingOccurrences(of: "/", with: " / ") }
    if let range = value.range(of: ":user/") { return "User · " + value[range.upperBound...] }
    if let range = value.range(of: ":role/") { return "Role · " + value[range.upperBound...] }
    return value
}

private extension ResourceEvent {
    var primaryResource: String {
        if action == "RunTask", let task = resourceIds.first(where: { $0.contains(":task/") }) { return task }
        return resourceIds.first ?? "Resource ID unavailable"
    }

    var compactTitle: String {
        let actions = [
            "RunInstances": "Launch instance", "CreateVolume": "Create volume",
            "CreateNatGateway": "Create NAT gateway", "CreateDBInstance": "Create database",
            "CreateDBCluster": "Create database cluster", "CreateFunction": "Create function",
            "CreateFunction20150331": "Create function", "UpdateService": "Update service",
            "CreateService": "Create service", "RegisterTaskDefinition": "Register task definition",
            "RunTask": "Run task", "PutImage": "Push image", "CreateLogGroup": "Create log group",
            "CreateLogStream": "Create log stream", "DeleteService": "Delete service"
        ]
        let name = actions[action] ?? action
        return "\(service?.uppercased() ?? "AWS") · \(name)"
    }
}
