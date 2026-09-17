import Charts
import SwiftUI

struct SpendingOverview: View {
    @Environment(\.colorScheme) private var colorScheme
    let snapshot: Snapshot
    let totals: [DailyTotal]

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 18) {
                summary
                if !totals.isEmpty {
                    Divider().opacity(0.5)
                    dailySpend
                }
            }.modifier(CloudCard())
            if !snapshot.analysis.anomalies.isEmpty || !(snapshot.idleAlerts?.isEmpty ?? true) {
                alerts.modifier(CloudCard())
            }
            VStack(alignment: .leading, spacing: 6) {
                PanelHeading(title: "By service", detail: "Month to date")
                ForEach(snapshot.analysis.topServices.prefix(6)) { service in
                    ServiceSpendRow(service: service, currencyCode: snapshot.analysis.currency,
                                    maximum: snapshot.analysis.topServices.map(\.value).max() ?? 1)
                }
            }.modifier(CloudCard())
            DisclosureGroup("Billing details") {
                VStack(alignment: .leading, spacing: 7) {
                    Text("AWS Cost Explorer · \(snapshot.analysis.costMetric)")
                    Text("Data is delayed and excludes today (UTC). \(snapshot.analysis.billingProvisional ? "Current charges are provisional." : "")")
                    Text(snapshot.analysis.anomalyCoverage == "available" ? "Spending alerts compare against three matching weekdays." : "Collecting enough history to detect spending changes.")
                    ForEach(snapshot.warnings, id: \.self) { Text($0) }
                }.font(.caption).foregroundStyle(.secondary).padding(.top, 6).textSelection(.enabled)
            }.font(.caption).foregroundStyle(.secondary)
        }

    }

    private var summary: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text("Month to date").font(.system(size: 12, weight: .medium))
                Spacer()
                Text(snapshot.isStale ? "Needs refresh" : "Through \(billingDate)")
                    .font(.caption).foregroundStyle(snapshot.isStale ? Color.orange : Color.secondary)
            }
            HStack(alignment: .firstTextBaseline, spacing: 7) {
                Text(currency(snapshot.analysis.displayedSpend, code: snapshot.analysis.currency))
                    .font(.system(size: 36, weight: .medium)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.6)
                Text(snapshot.analysis.currency).font(.caption).foregroundStyle(.secondary)
                Spacer()
            }
            Text(snapshot.analysis.spendBeforeCredits == nil ? "After credits" : "Before credits & refunds")
                .font(.caption).foregroundStyle(.secondary)
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Month forecast").font(.caption).foregroundStyle(.secondary)
                    Text(snapshot.forecast.map { currency($0.monthTotal, code: snapshot.analysis.currency) } ?? "Unavailable")
                        .font(.system(size: 13, weight: .medium)).monospacedDigit()
                }
                Spacer()
                if let credits = snapshot.analysis.credits {
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("Credits \(currency(credits, code: snapshot.analysis.currency))").font(.caption).foregroundStyle(.secondary)
                        Text("Net \(currency(snapshot.analysis.monthToDate, code: snapshot.analysis.currency))")
                            .font(.system(size: 13, weight: .medium)).monospacedDigit()
                        if let refunds = snapshot.analysis.refunds, (Double(refunds) ?? 0) != 0 {
                            Text("Refunds \(currency(refunds, code: snapshot.analysis.currency))").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }.padding(.top, 5)
        }
    }

    private var billingDate: String {
        guard let raw = snapshot.analysis.billingThrough,
              let date = parseTimestamp(raw + "T12:00:00Z") else { return "unknown date" }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }

    private var dailySpend: some View {
        VStack(alignment: .leading, spacing: 8) {
            PanelHeading(title: "Daily spend", detail: "Last \(totals.count) days")
            Chart(totals) { day in
                BarMark(x: .value("Day", day.day), y: .value("Spend", day.value))
                    .foregroundStyle(day.id == totals.last?.id ? Color.accentColor : Color.primary.opacity(colorScheme == .dark ? 0.34 : 0.18))
                    .cornerRadius(2)
                    .accessibilityLabel(day.day)
                    .accessibilityValue(currency(day.amount, code: snapshot.analysis.currency))
            }
            .chartXAxis(.hidden)
            .chartYAxis {
                AxisMarks(position: .trailing, values: .automatic(desiredCount: 2)) { value in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5, dash: [2, 3])).foregroundStyle(Color.secondary.opacity(0.15))
                    AxisValueLabel {
                        if let amount = value.as(Double.self) { Text(amount.formatted(.number.precision(.fractionLength(0)))).font(.system(size: 9)) }
                    }
                }
            }
            .frame(height: 64)
            HStack {
                Text(shortDate(totals.first?.day))
                Spacer()
                Text(shortDate(totals.last?.day))
            }.font(.system(size: 10)).foregroundStyle(.secondary)
        }
    }

    private var alerts: some View {
        VStack(alignment: .leading, spacing: 10) {
            PanelHeading(title: "Needs attention", detail: "")
            ForEach(snapshot.analysis.anomalies) { anomaly in
                DisclosureGroup {
                    Text("\(anomaly.region) · \(anomaly.day)\nAbove the median of three matching weekdays. Cause needs investigation.")
                        .font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                } label: {
                    HStack {
                        Image(systemName: "exclamationmark.circle").foregroundStyle(.orange)
                        Text(anomaly.service).lineLimit(1)
                        Spacer()
                        Text("+" + currency(anomaly.increase, code: anomaly.currency)).monospacedDigit()
                    }.font(.caption)
                }
            }
            ForEach(snapshot.idleAlerts ?? []) { idle in
                DisclosureGroup {
                    Text("\(idle.resourceId)\n\(idle.region) · AWS recommends \(idle.action.lowercased()). Review ownership and dependencies first.")
                        .font(.caption).foregroundStyle(.secondary).textSelection(.enabled).padding(.top, 4)
                } label: {
                    HStack {
                        Image(systemName: "exclamationmark.circle").foregroundStyle(.orange)
                        Text("Idle resource")
                        Spacer()
                        Text("~\(currency(idle.monthlySavings, code: idle.currency))/mo").monospacedDigit()
                    }.font(.caption)
                }
            }
        }
    }

    private func shortDate(_ raw: String?) -> String {
        guard let raw, let date = parseTimestamp(raw + "T12:00:00Z") else { return "" }
        return date.formatted(.dateTime.month(.abbreviated).day())
    }
}

private struct ServiceSpendRow: View {
    @Environment(\.colorScheme) private var colorScheme
    let service: ServiceCost
    let currencyCode: String
    let maximum: Double
    var body: some View {
        VStack(spacing: 6) {
            HStack {
                Text(service.shortName).lineLimit(1).help(service.service)
                Spacer()
                Text(currency(service.amount, code: currencyCode)).monospacedDigit()
            }.font(.system(size: 12))
            GeometryReader { geometry in
                Rectangle().fill(Color.primary.opacity(colorScheme == .dark ? 0.34 : 0.16))
                    .frame(width: geometry.size.width * max(0, min(1, service.value / max(maximum, 1))))
            }.frame(height: 2).accessibilityHidden(true)
        }.padding(.vertical, 5).accessibilityElement(children: .combine)
    }
}
