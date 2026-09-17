import AppKit
import SwiftUI

enum PanelTab: String, CaseIterable { case overview = "Overview", changes = "Changes", savings = "Savings", inbox = "Inbox" }

struct MenuPanel: View {
    static let width: CGFloat = 420
    static var height: CGFloat { min(640, (NSScreen.main?.visibleFrame.height ?? 800) - 60) }
    @ObservedObject var model: AgentModel
    @Environment(\.openWindow) private var openWindow
    @State private var tab: PanelTab = .overview
    @State private var confirmSavings = false
    @State private var includeRoutine = false

    init(model: AgentModel, initialTab: PanelTab = .overview) {
        self.model = model
        _tab = State(initialValue: initialTab)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            if model.needsSignIn { reconnectBanner }
            if model.status != nil {
                Picker("View", selection: $tab) {
                    ForEach(PanelTab.allCases, id: \.self) { item in
                        Text(item == .inbox && unreadCount > 0 ? "Inbox \(unreadCount > 99 ? "99+" : String(unreadCount))" : item.rawValue).tag(item)
                    }
                }
                .pickerStyle(.segmented).labelsHidden()
                .padding(.horizontal, 18).padding(.bottom, 14)
                if tab == .inbox {
                    InboxView(model: model, selectedAlert: model.isPreview && CommandLine.arguments.contains("--inbox-detail") ? model.inboxPage?.alerts.first : nil)
                } else if let snapshot = model.status?.snapshot {
                  ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        if let error = model.error, !model.needsSignIn { InlineNotice(text: error, warning: true) }
                        switch tab {
                        case .overview: SpendingOverview(snapshot: snapshot, totals: model.status?.dailyTotals ?? [])
                        case .changes: activity
                        case .savings: savings(snapshot)
                        case .inbox: EmptyView()
                        }
                    }.padding(.horizontal, 20).padding(.bottom, 20)
                  }.id(tab)
                } else {
                    emptyState
                }
            } else { emptyState }
            Divider()
            footer
        }
        .frame(width: Self.width, height: Self.height)
        .background { MacPanelBackground() }
        .alert("Enable AWS savings analysis?", isPresented: $confirmSavings) {
            Button("Cancel", role: .cancel) { }
            Button("Enable for this account") { Task { await model.enableSavings() } }
        } message: {
            Text("Account \(model.status?.snapshot?.accountId ?? "") only. Enables standard Compute Optimizer and Cost Optimization Hub recommendations. AWS may create service-linked roles. Does not enroll member accounts or enable paid enhanced metrics. Your infrastructure is not resized or deleted.")
        }
    }

    private var reconnectBanner: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("AWS sign-in required", systemImage: "person.crop.circle.badge.exclamationmark")
                .font(.system(size: 12, weight: .semibold))
            Text(model.status == nil ? "Your AWS session expired. Reconnect to load your account." : "Your AWS session expired. Showing the last collected data.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                if model.settings.connectionMethod == "credentials" || model.settings.connectionMethod == "profile" {
                    Button("Update credentials") { showWindow("settings") }.controlSize(.small)
                    Button("Try again") { Task { await model.retryConnection() } }
                        .controlSize(.small).disabled(model.busy || model.configuring)
                } else {
                    Button(model.busy ? "Signing in…" : "Sign in to AWS") { Task { await model.reconnect() } }
                        .controlSize(.small).disabled(model.busy || model.configuring)
                    Button("Connection settings") { showWindow("settings") }.controlSize(.small)
                }
            }
            if let error = model.error, error != BridgeError.authenticationRequired.localizedDescription {
                Text(error).font(.caption).foregroundStyle(.secondary).lineLimit(3)
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
            .padding(12).background(Color.orange.opacity(0.09), in: RoundedRectangle(cornerRadius: 8))
            .padding(.horizontal, 18).padding(.bottom, 12)
    }

    private var header: some View {
        HStack(spacing: 8) {
            BrandMark(size: 23)
            Text("Cloudwake").font(.system(size: 13, weight: .semibold))
            Spacer()
            if model.settings.demo {
                Text("Demo").font(.caption).foregroundStyle(.orange)
            } else if let snapshot = model.status?.snapshot {
                Text("AWS · " + snapshot.accountId).font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
                    .help("Connected AWS account \(snapshot.accountId)").textSelection(.enabled)
            }
            Button {
                Task {
                    if tab == .inbox { await model.loadInbox() }
                    else if tab == .changes { await model.refreshHistory() }
                    else { await model.refresh() }
                }
            } label: {
                if model.busy { ProgressView().controlSize(.mini).frame(width: 24, height: 24) }
                else { Image(systemName: "arrow.clockwise").frame(width: 24, height: 24) }
            }.disabled(model.busy || (tab != .inbox && model.status?.snapshot == nil))
                .accessibilityLabel(refreshLabel).help(refreshLabel)
            Button { showWindow("settings") } label: { Image(systemName: "gearshape").frame(width: 24, height: 24) }
                .accessibilityLabel("Open Cloudwake settings").help("Settings")
        }.buttonStyle(.plain).padding(.horizontal, 18).padding(.vertical, 13)
    }

    private var unreadCount: Int { model.inboxPage?.counts.unread ?? model.status?.inboxSummary?.unread ?? 0 }
    private var refreshLabel: String {
        tab == .inbox ? "Refresh inbox" : (tab == .changes ? "Refresh resource activity" : "Refresh spending")
    }

    private var activity: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Recent activity").font(.system(size: 12, weight: .semibold))
                Spacer()
                Toggle("Routine activity", isOn: $includeRoutine).toggleStyle(.checkbox).font(.caption)
                    .help("Include log streams and routine networking changes")
            }
            if let activity = model.status?.activity {
                HStack {
                    Text(activity.regions.map(\.region).joined(separator: ", "))
                    Spacer()
                    if let checked = activity.checkedAt.flatMap(parseTimestamp) {
                        Text("Checked \(checked.formatted(date: .omitted, time: .shortened))")
                    }
                }.font(.caption2).foregroundStyle(.secondary)
                if activity.regions.contains(where: \.backfillPending) {
                    InlineNotice(text: "Importing older activity…", warning: false)
                }
                ForEach(activity.warnings, id: \.self) { InlineNotice(text: $0, warning: true) }
            }
            let events = (includeRoutine ? (model.status?.allEvents ?? model.status?.events) : model.status?.events) ?? []
            if events.isEmpty {
                QuietEmptyState(title: "No activity to show", detail: "Refresh to check CloudTrail. Activity is checked every five minutes while monitoring.", symbol: "clock")
            }
            LazyVStack(spacing: 0) {
                ForEach(events) { event in
                    ActivityRow(event: event)
                    Divider()
                }
            }
            Text("CloudTrail API calls · Provisioning status is unverified")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    private func savings(_ snapshot: Snapshot) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 10) {
                PanelHeading(title: "AWS recommendations", detail: snapshot.recommendations.isEmpty ? "" : "\(snapshot.recommendations.count) to review")
                if snapshot.recommendations.isEmpty {
                    if snapshot.savingsStatus?.state == "available" {
                        Text("No savings estimates yet.").font(.system(size: 13))
                        Text("AWS may still be analyzing usage, or have no supported recommendations.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        InlineNotice(text: snapshot.savingsStatus?.message ?? "Savings analysis has not been checked yet.", warning: true)
                        if !model.settings.demo {
                            Button("Enable AWS analysis…") { confirmSavings = true }.disabled(model.busy)
                        }
                    }
                    if !model.settings.demo {
                        Link("View in AWS", destination: URL(string: "https://console.aws.amazon.com/costmanagement/home#/cost-optimization-hub")!).font(.caption)
                    }
                } else {
                    Text("Estimated monthly savings · May overlap").font(.caption).foregroundStyle(.secondary)
                    VStack(spacing: 0) {
                        ForEach(snapshot.recommendations.prefix(20)) { recommendation in
                            RecommendationRow(recommendation: recommendation)
                            Divider()
                        }
                    }
                }
            }
            if let monitoring = snapshot.unusedMonitoring {
                VStack(alignment: .leading, spacing: 10) {
                    PanelHeading(title: "Unused resources", detail: monitoring.enabled ? "\(monitoring.thresholdDays)-day alert" : "Alerts paused")
                    ForEach(monitoring.warnings, id: \.self) { InlineNotice(text: $0, warning: true) }
                    if snapshot.unusedResources?.isEmpty ?? true {
                        Text(monitoring.warnings.isEmpty ? "None found in the latest check." : "Some checks could not complete.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    VStack(spacing: 0) {
                        ForEach((snapshot.unusedResources ?? []).prefix(20)) { resource in
                            UnusedResourceRow(resource: resource)
                            Divider()
                        }
                    }
                    DisclosureGroup("What’s monitored") {
                        Text("Unattached EBS volumes in \(monitoring.regions.joined(separator: ", ")), plus AWS idle recommendations. Checks are sampled while this Mac is awake. Creator identity comes from CloudTrail; a deployment role may not identify a person.")
                            .font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                    }.font(.caption).foregroundStyle(.secondary)
                }
            }
            if let leads = snapshot.reviewLeads, !leads.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    PanelHeading(title: "Review spending", detail: "Savings unmeasured")
                    ForEach(leads) { lead in
                        DisclosureGroup {
                            Text(lead.detail).font(.caption).foregroundStyle(.secondary).padding(.vertical, 6)
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(lead.title).font(.system(size: 12))
                                Text("\(currency(lead.periodSpend, code: lead.currency)) spent this month")
                                    .font(.caption).foregroundStyle(.secondary)
                            }.padding(.vertical, 8)
                        }
                        Divider()
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Spacer()
            QuietEmptyState(title: model.busy ? "Loading your account…" : "Connect an AWS account",
                            detail: model.error ?? "See spending and resource activity from your menu bar.", symbol: "cloud")
            if model.busy { ProgressView().controlSize(.small) }
            else { Button("Open Settings") { showWindow("settings") }.buttonStyle(.borderedProminent) }
            Spacer()
        }.padding(28).frame(maxWidth: .infinity)
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let monitoring = model.status?.monitoring, !monitoring.healthy {
                InlineNotice(text: monitoring.message, warning: true)
            }
            if let notice = model.notice {
                Text(notice).font(.caption2).foregroundStyle(.secondary).lineLimit(2).help(notice)
            }
            if let notifications = model.status?.notifications, notifications.failed > 0 {
                InlineNotice(text: "\(notifications.failed) email deliveries need attention.", warning: true)
            }
            HStack(spacing: 6) {
                Circle().fill(model.needsSignIn ? Color.orange : (model.isMonitoring ? Color.green : Color.secondary.opacity(0.5))).frame(width: 5, height: 5).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.needsSignIn ? "AWS sign-in required" : (model.usesCloudMonitoring ? (model.isMonitoring ? "Monitoring in AWS" : "Cloud needs attention") : (model.isMonitoring ? "Monitoring" : "Paused")))
                        .font(.system(size: 11, weight: .medium))
                    if let date = model.status?.snapshot?.collectedDate {
                        Text("\(model.needsSignIn ? "Last data" : "Updated") \(date.formatted(date: .abbreviated, time: .shortened))")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                }
                Spacer()
                if model.ownsWorker {
                    Button("Pause") { model.stopWorker() }.controlSize(.small)
                } else if !model.needsSignIn && !model.isMonitoring && !model.usesCloudMonitoring {
                    Button("Start monitoring") { Task { await model.startWorker() } }.controlSize(.small).disabled(model.busy)
                }
                Button("Report") { Task { await model.openReport() } }.controlSize(.small)
                    .disabled(model.busy || model.status?.snapshot == nil)
                Menu {
                    Button("Ask about spending…") { showWindow("ask") }.disabled(model.status?.snapshot == nil)
                    if !model.usesCloudMonitoring {
                        Button("Open email previews") { model.openPreviews() }.disabled(model.status == nil)
                    } else {
                        Text("Runs while this Mac is asleep · Email disabled")
                    }
                    if model.status?.notifications.delivery == "preview" { Text("Email delivery: preview only") }
                    if model.isMonitoring && !model.ownsWorker && !model.usesCloudMonitoring { Text("Monitoring managed by another process") }
                    Divider()
                    Button("Open project folder") { NSWorkspace.shared.open(URL(fileURLWithPath: model.settings.projectPath)) }
                    Button("Quit Cloudwake") { model.shutdown(); NSApplication.shared.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "ellipsis").frame(width: 24, height: 24) }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).frame(width: 24).accessibilityLabel("More options")
            }
        }.padding(.horizontal, 18).padding(.vertical, 12)
    }

    private func showWindow(_ id: String) {
        openWindow(id: id)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
}
