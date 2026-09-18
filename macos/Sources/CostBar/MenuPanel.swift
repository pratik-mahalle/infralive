import AppKit
import SwiftUI

enum PanelTab: String, CaseIterable { case overview = "Overview", changes = "Changes", savings = "Savings", inbox = "Inbox" }

struct MenuPanel: View {
    static let width: CGFloat = 390
    static var height: CGFloat { min(620, (NSScreen.main?.visibleFrame.height ?? 800) - 60) }
    @ObservedObject var model: AgentModel
    var workspace: AccountWorkspace? = nil
    @Environment(\.openWindow) private var openWindow
    @State private var tab: PanelTab = .overview
    @State private var confirmSavings = false
    @State private var includeRoutine = false

    init(model: AgentModel, initialTab: PanelTab = .overview, workspace: AccountWorkspace? = nil) {
        self.model = model
        self.workspace = workspace
        _tab = State(initialValue: initialTab)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            if model.awaitingConnection {
                ScrollView {
                    ConnectionPanel(model: model, workspace: workspace)
                        .padding(.horizontal, 20).padding(.bottom, 20)
                }
                Divider()
                HStack {
                    Spacer()
                    Button("Quit Cloudwake") { NSApplication.shared.terminate(nil) }
                        .controlSize(.small).keyboardShortcut("q")
                }.padding(.horizontal, 16).padding(.vertical, 10)
            } else {
                if model.needsSignIn { reconnectBanner }
                if model.status != nil {
                    if tab == .inbox {
                        InboxView(model: model, selectedAlert: model.isPreview && CommandLine.arguments.contains("--inbox-detail") ? model.inboxPage?.alerts.first : nil)
                    } else if let snapshot = model.status?.snapshot {
                      ScrollView {
                        VStack(alignment: .leading, spacing: 18) {
                            if let error = model.error, !model.needsSignIn { InlineNotice(text: error, warning: true) }
                            switch tab {
                            case .overview: SpendingOverview(snapshot: snapshot, totals: model.status?.dailyTotals ?? [], showSavings: { tab = .savings })
                            case .changes: activity
                            case .savings: savings(snapshot)
                            case .inbox: EmptyView()
                            }
                        }.padding(.horizontal, 16).padding(.bottom, 18)
                      }.id(tab)
                    } else {
                        emptyState
                    }
                } else { emptyState }
                if model.status != nil { navigation.padding(.top, 8) }
                footer
            }
        }
        .frame(width: Self.width, height: model.awaitingConnection ? min(520, Self.height) : Self.height)
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
            if let workspace, !model.awaitingConnection {
                AccountPicker(workspace: workspace, compact: true).font(.system(size: 12, weight: .medium))
            } else {
                Label(model.awaitingConnection ? "Cloudwake" : "AWS account", systemImage: "cloud")
                    .font(.system(size: 12, weight: .medium))
                Spacer()
                if model.settings.demo { Text("Demo").font(.caption).foregroundStyle(.secondary) }
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
        }.buttonStyle(.plain).padding(.horizontal, 16).padding(.vertical, 10)
    }

    private var navigation: some View {
        HStack(spacing: 3) {
            ForEach(PanelTab.allCases, id: \.self) { item in
                Button { tab = item } label: {
                    HStack(spacing: 4) {
                        Text(item.rawValue)
                        if item == .inbox && unreadCount > 0 {
                            Text("\(min(unreadCount, 99))")
                                .font(.system(size: 9, weight: .semibold)).monospacedDigit()
                                .padding(.horizontal, 4).padding(.vertical, 1)
                                .background(Color.accentColor.opacity(0.12), in: Capsule())
                                .foregroundStyle(Color.accentColor)
                        }
                    }
                    .font(.system(size: 11, weight: tab == item ? .semibold : .medium))
                    .frame(maxWidth: .infinity).frame(height: 29)
                    .foregroundStyle(tab == item ? Color.primary : Color.secondary)
                    .background {
                        if tab == item {
                            RoundedRectangle(cornerRadius: 7).fill(.background.opacity(0.85))
                                .shadow(color: .black.opacity(0.06), radius: 2, y: 1)
                        }
                    }
                    .contentShape(RoundedRectangle(cornerRadius: 7))
                }.buttonStyle(.plain).accessibilityLabel(item.rawValue)
                    .accessibilityValue(item == .inbox ? "\(unreadCount) unread" : "")
                    .accessibilityAddTraits(tab == item ? [.isSelected] : [])
                    .keyboardShortcut(KeyEquivalent(Character(String((PanelTab.allCases.firstIndex(of: item) ?? 0) + 1))), modifiers: .command)
                    .help(item == .inbox ? "Your alerts, saved for later" : item.rawValue)
            }
        }.padding(3).background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 10))
            .padding(.horizontal, 16)
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
            LazyVStack(spacing: 7) {
                ForEach(events) { event in
                    ActivityRow(event: event).modifier(CloudRow())
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
                    VStack(spacing: 7) {
                        ForEach(snapshot.recommendations.prefix(20)) { recommendation in
                            RecommendationRow(recommendation: recommendation).modifier(CloudRow())
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
                    VStack(spacing: 7) {
                        ForEach((snapshot.unusedResources ?? []).prefix(20)) { resource in
                            UnusedResourceRow(resource: resource).modifier(CloudRow())
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
            HStack(spacing: 6) {
                Image(systemName: "cloud").foregroundStyle(.secondary).accessibilityHidden(true)
                Circle().fill(model.needsSignIn ? Color.orange : (model.isMonitoring ? Color.green : Color.secondary.opacity(0.5))).frame(width: 5, height: 5).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.needsSignIn ? "Sign-in required" : (model.usesCloudMonitoring ? (model.isMonitoring ? "Monitoring in AWS" : "Cloud needs attention") : (model.isMonitoring ? "Cloudwake · Monitoring" : "Cloudwake · Paused")))
                        .font(.system(size: 11, weight: .medium))
                    if let date = model.status?.snapshot?.collectedDate {
                        Text("\(model.needsSignIn ? "Last data" : "Synced") \(date.formatted(date: .omitted, time: .shortened))")
                            .font(.system(size: 10)).foregroundStyle(.secondary).help(date.formatted(date: .complete, time: .shortened))
                    }
                }
                Spacer()
                if model.ownsWorker {
                    Button("Pause") { model.stopWorker() }.controlSize(.small)
                } else if !model.needsSignIn && !model.isMonitoring && !model.usesCloudMonitoring {
                    Button("Start monitoring") { Task { await model.startWorker() } }.controlSize(.small).disabled(model.busy)
                }
                Menu {
                    Button("Open spending report") { Task { await model.openReport() } }
                        .disabled(model.busy || model.status?.snapshot == nil)
                    Button("Ask about spending…") { showWindow("ask") }.disabled(model.status?.snapshot == nil)
                    if model.usesCloudMonitoring { Text("Runs while this Mac is asleep") }
                    if model.isMonitoring && !model.ownsWorker && !model.usesCloudMonitoring { Text("Monitoring managed by another process") }
                    Divider()
                    Button("Open project folder") { NSWorkspace.shared.open(URL(fileURLWithPath: model.settings.projectPath)) }
                    Button("Quit Cloudwake") { model.shutdown(); NSApplication.shared.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "ellipsis").frame(width: 24, height: 24) }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).frame(width: 24).accessibilityLabel("More options")
            }
        }.padding(.horizontal, 16).padding(.vertical, 10)
    }

    private func showWindow(_ id: String) {
        openWindow(id: id)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }
}
