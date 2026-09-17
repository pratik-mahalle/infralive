import AppKit
import SwiftUI

struct SettingsPanel: View {
    @ObservedObject var model: AgentModel
    @State private var draft: AgentSettings
    private let previewReview: ConnectionReview?
    private let workspace: AccountWorkspace?

    init(model: AgentModel, previewReview: ConnectionReview? = nil, workspace: AccountWorkspace? = nil) {
        self.model = model
        self.workspace = workspace
        self.previewReview = previewReview
        _draft = State(initialValue: model.settings)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 12) {
                    BrandMark()
                    VStack(alignment: .leading, spacing: 3) {
                        Text(model.awaitingConnection ? "Welcome to Cloudwake" : "Cloudwake Settings").font(.title2).fontWeight(.semibold)
                        Text(model.awaitingConnection ? "Connect AWS to see your spending and resource activity." : "AWS connection and notifications.").foregroundStyle(.secondary)
                    }
                }
                if let workspace, !model.awaitingConnection {
                    AccountSettings(workspace: workspace)
                    Divider()
                }
                ConnectionPanel(model: model, previewReview: previewReview, workspace: workspace)
                if !model.awaitingConnection {
                    Divider()
                    NotificationSettings(model: model, notifier: model.notifier)
                    Divider()
                    if let cloud = model.status?.monitoring {
                        VStack(alignment: .leading, spacing: 7) {
                            Label("Always-on monitoring", systemImage: "cloud").fontWeight(.medium)
                            Text("\(cloud.functionName) · \(cloud.region)").font(.caption).foregroundStyle(.secondary)
                            Text(cloud.message).font(.caption).foregroundStyle(.secondary)
                            Text("AWS checks activity every five minutes and costs every six hours. Closing this app does not stop the cloud monitor. Email is disabled.")
                                .font(.caption).foregroundStyle(.secondary)
                            Link("Open cloud monitor", destination: URL(string: "https://console.aws.amazon.com/lambda/home?region=\(cloud.region)#/functions/\(cloud.functionName)")!)
                        }
                        Divider()
                    }
                    DisclosureGroup("Advanced settings & demo") {
                        VStack(alignment: .leading, spacing: 14) {
                            Toggle("Use demo data", isOn: $draft.demo).toggleStyle(.switch).tint(.accentColor)
                            pathField("Agent project folder", value: $draft.projectPath, directory: true) {
                                draft.pythonPath = draft.projectPath + "/.venv/bin/python"
                                draft.configPath = draft.projectPath + "/config.toml"
                            }
                            pathField("Python executable", value: $draft.pythonPath, directory: false)
                            if !draft.demo {
                                pathField("AWS configuration file", value: $draft.configPath, directory: false)
                                Button("Create / open configuration") { openConfig() }
                            }
                            Button("Apply advanced settings") { Task { await model.save(draft) } }
                                .disabled(model.busy || model.asking || model.ownsWorker || model.configuring)
                        }.padding(.top, 12)
                    }
                    Divider()
                    Text(model.usesCloudMonitoring ? "The menu reads private cloud state every 30 seconds. Mac banners appear while this app is open; the cloud inbox keeps collecting when it is closed." : "The menu reads local data every 30 seconds. Refresh collects AWS costs. Start runs the worker and its configured email delivery while this app is open. Monitoring pauses when your Mac sleeps.")
                        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    if model.ownsWorker {
                        Label("Stop the worker before changing settings.", systemImage: "info.circle")
                            .font(.caption).foregroundStyle(.orange)
                    }
                }
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
                }
                HStack {
                    Button("Open setup guide") {
                        NSWorkspace.shared.open(URL(fileURLWithPath: draft.projectPath + "/README.md"))
                    }
                }
            }.padding(26).frame(width: 550)
        }.frame(width: 550, height: min(720, (NSScreen.main?.visibleFrame.height ?? 800) - 80))
            .background { MacPanelBackground() }
            .onChange(of: model.settings) { draft = $0 }
    }

    private func pathField(_ title: String, value: Binding<String>, directory: Bool,
                           afterSelection: @escaping () -> Void = {}) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 12, weight: .medium))
            HStack {
                TextField(title, text: value).textFieldStyle(.roundedBorder)
                    .font(.system(size: 11, design: .monospaced)).labelsHidden()
                    .accessibilityLabel(title)
                Button("Choose…") {
                    let panel = NSOpenPanel()
                    panel.canChooseDirectories = directory
                    panel.canChooseFiles = !directory
                    panel.allowsMultipleSelection = false
                    panel.prompt = "Choose"
                    if panel.runModal() == .OK, let url = panel.url {
                        value.wrappedValue = url.path
                        afterSelection()
                    }
                }
            }
        }
    }

    private func openConfig() {
        do {
            if !FileManager.default.fileExists(atPath: draft.configPath) {
                try FileManager.default.copyItem(atPath: draft.projectPath + "/config.example.toml", toPath: draft.configPath)
            }
            NSWorkspace.shared.open(URL(fileURLWithPath: draft.configPath))
        } catch { model.error = error.localizedDescription }
    }
}

private struct NotificationSettings: View {
    @ObservedObject var model: AgentModel
    @ObservedObject var notifier: DesktopNotifier
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Mac notifications", systemImage: "bell.badge").fontWeight(.medium)
                Spacer()
                Text(notifier.permission).font(.caption).foregroundStyle(.secondary)
                if notifier.enabled {
                    Button("Pause") { notifier.disable() }
                } else {
                    Button("Enable…") {
                        if let status = model.status { Task { await notifier.enable(status: status) } }
                    }.disabled(model.status == nil || model.busy)
                }
            }
            Text("New resource creations, spending increases and idle-resource costs. macOS will ask for permission. Alerts begin from now; deployment bursts are grouped.")
                .font(.caption).foregroundStyle(.secondary)
            if notifier.permission.contains("Blocked") {
                Text("Allow Cloudwake in System Settings → Notifications.").font(.caption).foregroundStyle(.orange)
            }
            if let error = notifier.lastError { Text(error).font(.caption).foregroundStyle(.red) }
        }
    }
}

struct AskPanel: View {
    @ObservedObject var model: AgentModel
    @State private var question = "Why did our spending increase?"

    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            HStack {
                Label("Ask about spending", systemImage: "text.bubble")
                    .font(.title3).fontWeight(.semibold)
                Spacer()
                Text(model.settings.demo ? "DEMO" : "AWS").font(.caption).foregroundStyle(.secondary)
            }
            Text("Answers use collected evidence. Configure Bedrock for natural-language investigation; otherwise the agent returns a local evidence report.")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                TextField("Ask about spending, resources or savings", text: $question)
                    .textFieldStyle(.roundedBorder).onSubmit { submit() }
                Button("Ask") { submit() }.buttonStyle(.borderedProminent).tint(.accentColor)
                    .disabled(model.asking || model.busy || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            HStack {
                suggestion("Where can we save?")
                suggestion("Who created new resources?")
            }
            Divider()
            if model.asking {
                HStack { ProgressView().controlSize(.small); Text("Reading the evidence…").foregroundStyle(.secondary) }
                Spacer()
            } else {
                ScrollView {
                    Text(model.answer.isEmpty ? "Your answer will appear here." : model.answer)
                        .font(.system(size: 12)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }.padding(24).frame(minWidth: 570, minHeight: 380)
    }

    private func suggestion(_ text: String) -> some View {
        Button(text) { question = text; submit() }.controlSize(.small).disabled(model.asking || model.busy)
    }

    private func submit() { Task { await model.ask(question) } }
}
