import SwiftUI

struct TeamSpendingSection: View {
    let spending: TeamSpending?
    let dimension: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let spending, let group = spending.dimensions.first(where: { $0.id == dimension }) {
                PanelHeading(title: "By \(dimension)", detail: "Tag: \(group.tagKey)")
                ForEach(group.groups) { item in
                    HStack {
                        Text(item.name + (!item.unassigned && item.name == "Unassigned" ? " (tag value)" : ""))
                            .lineLimit(2).textSelection(.enabled)
                        Spacer()
                        Text(currency(item.amount, code: spending.currency)).monospacedDigit()
                    }.font(.system(size: 12)).padding(.vertical, 5)
                    Divider()
                }
                Text(spending.basis).font(.caption2).foregroundStyle(.secondary)
                if let message = group.message {
                    InlineNotice(text: message, warning: true)
                    Text("Unassigned includes charges that cannot currently be attributed using this billing tag.")
                        .font(.caption2).foregroundStyle(.secondary)
                    Link("Manage billing tags", destination: URL(string: "https://console.aws.amazon.com/billing/home#/tags")!)
                        .font(.caption)
                } else {
                    Text("Unassigned has no billing tag value. Project and owner show separate views of the same charges.")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            } else {
                QuietEmptyState(title: "Team spending not loaded", detail: "Refresh to collect Project and Owner billing tags.", symbol: "person.2")
            }
        }
    }
}
