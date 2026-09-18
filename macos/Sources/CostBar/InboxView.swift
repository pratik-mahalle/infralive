import AppKit
import SwiftUI

struct InboxView: View {
    @ObservedObject var model: AgentModel
    @State private var selected: InboxAlert?
    var requestedSequence: Int? = nil
    @State private var didFocusRequest = false

    init(model: AgentModel, selectedAlert: InboxAlert? = nil, requestedSequence: Int? = nil) {
        self.model = model
        self.requestedSequence = requestedSequence
        _selected = State(initialValue: selectedAlert)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let error = model.inboxError {
                InlineNotice(text: error, warning: true).padding(.horizontal, 16)
            }
            if let alert = selected {
                detail(alert)
            } else {
                list
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task(id: model.status?.notificationFeedId) {
            await model.loadInbox(filter: requestedSequence == nil ? nil : .open)
            focusRequest()
        }
        .onChange(of: model.inboxPage?.alerts.map(\.id)) { _ in focusRequest() }
        .onChange(of: model.status?.notificationFeedId) { _ in selected = nil }
        .onChange(of: model.busy) { busy in
            if !busy && model.inboxPage == nil && model.inboxError == nil && !model.isPreview {
                Task { await model.loadInbox() }
            }
        }
    }

    private func focusRequest() {
        guard !didFocusRequest, let requestedSequence,
              let alert = model.inboxPage?.alerts.first(where: { $0.sequence == requestedSequence }) else { return }
        selected = alert
        didFocusRequest = true
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Picker("Alert status", selection: Binding(get: { model.inboxFilter }, set: { filter in
                    Task { await model.loadInbox(filter: filter) }
                })) {
                    ForEach(InboxFilter.allCases, id: \.self) { Text($0.title).tag($0) }
                }.pickerStyle(.menu).labelsHidden().fixedSize().disabled(model.busy)
                Spacer()
                if let page = model.inboxPage {
                    Text("\(count(page.counts)) \(model.inboxFilter.title.lowercased())")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.padding(.horizontal, 16)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 7) {
                    if let page = model.inboxPage, page.filter == model.inboxFilter {
                        if page.alerts.isEmpty {
                            QuietEmptyState(title: emptyTitle, detail: emptyDetail, symbol: "tray")
                        }
                        ForEach(page.alerts) { alert in
                            Button {
                                selected = alert
                                if alert.unread { Task { await model.updateInbox(alert, action: "read") } }
                            } label: { InboxRow(alert: alert) }
                                .buttonStyle(.plain).disabled(model.busy)
                                .accessibilityLabel("\(alert.unread ? "Unread. " : "")\(alert.title)")
                                .contextMenu {
                                    if alert.state == .reviewed {
                                        Button("Reopen") { Task { await model.updateInbox(alert, action: "reopen") } }
                                    } else {
                                        Button("Mark reviewed") { Task { await model.updateInbox(alert, action: "review") } }
                                        Button("Snooze for 1 day") { Task { await model.updateInbox(alert, action: "snooze") } }
                                        if alert.state == .snoozed {
                                            Button("Unsnooze") { Task { await model.updateInbox(alert, action: "reopen") } }
                                        } else {
                                            Button("Mark unread") { Task { await model.updateInbox(alert, action: "unread") } }
                                        }
                                    }
                                }
                        }
                    } else {
                        if model.busy { ProgressView().controlSize(.small).padding(.vertical, 24) }
                        else { Button("Load alerts") { Task { await model.loadInbox() } }.padding(.vertical, 24) }
                    }
                }.padding(.horizontal, 16).padding(.bottom, 12)
            }.id(model.inboxFilter.rawValue + String(model.inboxCursors.last ?? 0))
            if model.inboxCursors.count > 1 || model.inboxPage?.nextBefore != nil {
                HStack {
                    Button("Newer") { Task { await model.loadInbox(direction: -1) } }.disabled(model.busy || model.inboxCursors.count == 1)
                    Spacer()
                    Text("Page \(model.inboxCursors.count)").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Older") { Task { await model.loadInbox(direction: 1) } }.disabled(model.busy || model.inboxPage?.nextBefore == nil)
                }.controlSize(.small).padding(.horizontal, 16).padding(.bottom, 10)
            }
        }
    }

    private func detail(_ original: InboxAlert) -> some View {
        let alert = model.inboxPage?.alerts.first(where: { $0.id == original.id && $0.feedId == original.feedId }) ?? original
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button { selected = nil } label: { Label("All alerts", systemImage: "chevron.left") }
                    .buttonStyle(.plain)
                Spacer()
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(alert.title + "\n\n" + alert.body, forType: .string)
                } label: { Image(systemName: "doc.on.doc") }.buttonStyle(.plain).help("Copy alert details").accessibilityLabel("Copy alert details")
            }.font(.caption).padding(.horizontal, 16)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(alert.title).font(.system(size: 15, weight: .semibold)).textSelection(.enabled)
                    HStack {
                        Text(alert.kindLabel)
                        Spacer()
                        if let date = parseTimestamp(alert.createdAt) {
                            Text(date.formatted(date: .abbreviated, time: .shortened))
                        }
                    }.font(.caption2).foregroundStyle(.secondary)
                    if alert.state == .snoozed, let until = alert.snoozedUntil.flatMap(parseTimestamp) {
                        Label("Returns \(until.formatted(date: .abbreviated, time: .shortened))", systemImage: "clock")
                            .font(.caption).foregroundStyle(.secondary)
                    } else if alert.state == .reviewed {
                        Label("Reviewed", systemImage: "checkmark").font(.caption).foregroundStyle(.secondary)
                    }
                    Divider()
                    Text(alert.body).font(.system(size: 12)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).fixedSize(horizontal: false, vertical: true)
                }.padding(.horizontal, 16).padding(.bottom, 12)
            }
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    if alert.state == .reviewed {
                        Button("Reopen") { apply(alert, action: "reopen") }
                    } else {
                        Button("Mark reviewed") { apply(alert, action: "review") }
                            .buttonStyle(.borderedProminent)
                        Menu("Snooze") {
                            Button("1 hour") { apply(alert, action: "snooze", hours: 1) }
                            Button("1 day") { apply(alert, action: "snooze", hours: 24) }
                            Button("1 week") { apply(alert, action: "snooze", hours: 168) }
                        }.fixedSize()
                        if alert.state == .snoozed {
                            Button("Unsnooze") { apply(alert, action: "reopen") }
                        } else {
                            Button("Unread") { apply(alert, action: "unread") }.help("Mark unread")
                        }
                    }
                    Spacer(minLength: 0)
                }.controlSize(.small).disabled(model.busy)
                Text("Snooze returns this alert to the inbox. Delivery settings stay unchanged.")
                    .font(.system(size: 10)).foregroundStyle(.secondary)
            }.padding(.horizontal, 16).padding(.bottom, 14)
        }
    }

    private func apply(_ alert: InboxAlert, action: String, hours: Int = 24) {
        Task { if await model.updateInbox(alert, action: action, hours: hours) { selected = nil } }
    }
    private func count(_ counts: InboxCounts) -> Int {
        switch model.inboxFilter {
        case .open: return counts.open
        case .snoozed: return counts.snoozed
        case .reviewed: return counts.reviewed
        }
    }
    private var emptyTitle: String {
        switch model.inboxFilter {
        case .open: return "No open alerts"
        case .snoozed: return "Nothing snoozed"
        case .reviewed: return "Nothing reviewed yet"
        }
    }
    private var emptyDetail: String {
        switch model.inboxFilter {
        case .open: return "New resource, spending and unused-resource alerts will stay here until you review or snooze them."
        case .snoozed: return "Snoozed alerts return to Open when their time is up."
        case .reviewed: return "Reviewed alerts stay available here. You can reopen them at any time."
        }
    }
}

private struct InboxRow: View {
    let alert: InboxAlert
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Circle().fill(alert.unread && alert.state == .open ? Color.accentColor : Color.clear)
                .frame(width: 5, height: 5).padding(.top, 5).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(alert.kindLabel)
                    Spacer()
                    if let date = parseTimestamp(alert.createdAt) {
                        Text(date.formatted(.dateTime.month(.abbreviated).day().hour().minute()))
                    }
                }.font(.system(size: 10)).foregroundStyle(.secondary)
                Text(alert.title).font(.system(size: 12, weight: alert.unread ? .semibold : .regular))
                    .lineLimit(2).frame(maxWidth: .infinity, alignment: .leading)
                if let summary = alert.summary {
                    Text(summary).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                }
                if alert.state == .snoozed, let until = alert.snoozedUntil.flatMap(parseTimestamp) {
                    Text("Returns \(until.formatted(date: .abbreviated, time: .shortened))")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            Image(systemName: "chevron.right").font(.system(size: 9)).foregroundStyle(.tertiary).padding(.top, 20)
        }.modifier(CloudRow()).contentShape(Rectangle())
    }
}
