import AppKit
import SwiftUI

struct ProfileList: Decodable {
    let profiles: [String]
    let regions: [String]
    let ssoProfiles: [String]?
    let currentProfile: String?
}

struct ImportedCredentials: Decodable {
    let profile: String
    let temporary: Bool
}

struct ConnectionCheck: Decodable, Identifiable {
    let id: String
    let title: String
    let ready: Bool
    let detail: String
}

struct ConnectionReview: Decodable {
    let accountId: String
    let principal: String
    let profile: String
    let region: String
    let checks: [ConnectionCheck]
    var costsReady: Bool { checks.first(where: { $0.id == "costs" })?.ready == true }
}

struct ConnectionSaved: Decodable {
    let configPath: String
    let warning: String?
}

struct ConnectionPanel: View {
    @ObservedObject var model: AgentModel
    @State private var profiles: [String] = []
    @State private var regions = ["us-east-1", "ap-south-1", "eu-west-1"]
    @State private var profile = ""
    @State private var region = "us-east-1"
    @State private var review: ConnectionReview?
    @State private var working = false
    @State private var progress = ""
    @State private var error: String?
    @State private var connected = false
    @State private var confirmInstall = false
    @State private var useCredentials = false
    @State private var credentialDraft = CredentialDraft()
    @State private var ssoProfiles: [String] = []
    @State private var credentialNotice: String?
    private let bridge = AgentBridge()
    private let preview: Bool
    private let workspace: AccountWorkspace?
    @State private var accountName = ""

    init(model: AgentModel, previewReview: ConnectionReview? = nil, workspace: AccountWorkspace? = nil) {
        self.model = model
        self.workspace = workspace
        preview = model.isPreview || previewReview != nil
        _useCredentials = State(initialValue: model.isPreview && CommandLine.arguments.contains("--credentials"))
        if let value = previewReview {
            _review = State(initialValue: value)
            _profiles = State(initialValue: [value.profile])
            _profile = State(initialValue: value.profile)
            _region = State(initialValue: value.region)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(workspace == nil || model.awaitingConnection ? "Connect your AWS account" : "Add or reconnect an account", systemImage: "link.circle.fill")
                .font(.headline)
            Text("Use an AWS profile on this Mac, or paste access credentials. SSO is optional.")
                .font(.callout).foregroundStyle(.secondary)
            if !model.settings.demo && !model.awaitingConnection {
                Label("AWS connection saved" + (model.status?.snapshot.map { " · " + $0.accountId } ?? ""), systemImage: "checkmark.circle")
                    .font(.caption).foregroundStyle(.teal)
            }
            if workspace != nil {
                TextField("Account name (optional)", text: $accountName).textFieldStyle(.roundedBorder)
            }
            Picker("Connection method", selection: $useCredentials) {
                Text("AWS profile").tag(false)
                Text("Paste credentials").tag(true)
            }.pickerStyle(.segmented).labelsHidden()
            if useCredentials {
                CredentialEntry(draft: $credentialDraft)
            } else if profiles.isEmpty {
                Text("No AWS profiles found. Paste credentials above, or run aws configure in Terminal and reload.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Link("AWS profile setup ↗", destination: URL(string: "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html")!)
                    Button("Reload profiles") { Task { await loadProfiles() } }
                }
            } else {
                Picker("AWS profile", selection: $profile) {
                    Text("Choose a profile…").tag("")
                    ForEach(profiles, id: \.self) { Text($0.replacingOccurrences(of: "cloudwake-keychain-", with: "Saved credentials · ")).tag($0) }
                }
            }
            if useCredentials || !profiles.isEmpty {
                Picker("Resource region", selection: $region) {
                    ForEach(regions, id: \.self) { Text($0).tag($0) }
                }
                Text("Spending covers this account across regions. Creation alerts monitor the selected region.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button(review == nil ? "Check account" : "Check again") { Task { await check() } }
                        .buttonStyle(.borderedProminent).tint(.teal)
                        .disabled(useCredentials ? (credentialDraft.hasInput ? !credentialDraft.isReady : profile.isEmpty) : profile.isEmpty)
                    if !useCredentials && ssoProfiles.contains(profile) {
                        Button("Sign in with SSO…") { Task { await signIn() } }
                    }
                    Spacer()
                    Button { Task { await loadProfiles() } } label: { Image(systemName: "arrow.clockwise") }
                        .accessibilityLabel("Reload AWS profiles")
                }
                Text("Checking reads AWS account and feature status. Cost Explorer API charges may apply.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if let credentialNotice {
                Text(credentialNotice).font(.caption).foregroundStyle(.secondary)
            }
            if working {
                HStack(spacing: 8) { ProgressView().controlSize(.small); Text(progress).font(.caption) }
            }
            if let error {
                Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled)
            }
            if let review {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Account \(review.accountId)").font(.system(.headline, design: .monospaced))
                    Text(review.principal).font(.caption2).foregroundStyle(.secondary).textSelection(.enabled)
                }
                HStack {
                    if connected {
                        Label(workspace == nil ? "Connected. Press Start in the menu to begin monitoring." : "Connected. View monitoring status under Your accounts.", systemImage: "checkmark.circle.fill")
                            .font(.caption).foregroundStyle(.teal)
                    } else {
                        Button("Connect this account") { Task { await connect() } }
                            .buttonStyle(.borderedProminent).tint(.teal)
                            .disabled(!review.costsReady)
                    }
                }
                ForEach(review.checks) { item in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: item.ready ? "checkmark.circle.fill" : "exclamationmark.circle")
                            .foregroundStyle(item.ready ? .teal : .orange)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(item.title).font(.system(size: 12, weight: .medium))
                            Text(item.detail).font(.caption).foregroundStyle(.secondary)
                            if !item.ready {
                                if item.id == "events" {
                                    Button("Set up resource notifications…") { confirmInstall = true }
                                        .disabled(review.checks.first(where: { $0.id == "trail" })?.ready != true)
                                }
                                Link(item.id == "savings" ? "Open Cost Optimization Hub ↗" : "Open in AWS ↗", destination: consoleURL(item.id))
                                    .font(.caption)
                                if item.id == "savings" {
                                    Link("Open Compute Optimizer ↗", destination: URL(string: "https://console.aws.amazon.com/compute-optimizer/home")!)
                                        .font(.caption)
                                }
                            }
                        }
                        Spacer(minLength: 0)
                    }
                }
                Text("Connecting saves this account on your Mac. Enable Mac notifications in Settings for desktop alerts.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .disabled(working || model.busy || model.asking || (workspace == nil && model.ownsWorker))
        .task { if !preview { await loadProfiles() } }
        .onChange(of: profile) { _ in resetReview() }
        .onChange(of: region) { _ in resetReview() }
        .onChange(of: useCredentials) { _ in resetReview(); credentialNotice = nil; credentialDraft = CredentialDraft(); profile = "" }
        .onChange(of: credentialDraft) { _ in resetReview() }
        .onDisappear { credentialDraft = CredentialDraft(); model.configuring = false }
        .onChange(of: working) { model.configuring = $0 }
        .alert("Set up resource notifications?", isPresented: $confirmInstall) {
            Button("Cancel", role: .cancel) { }
            Button("Install in AWS") { Task { await install() } }
        } message: {
            Text("Account \(review?.accountId ?? "") · \(region)\nCreates the aws-cost-agent-events CloudFormation stack: an EventBridge rule, event queue, dead-letter queue, queue policy and alarm. AWS charges may apply. Uses your existing CloudTrail trail. Your profile needs deployment permissions. Existing stacks are reused.")
        }
    }

    private func resetReview() { review = nil; connected = false; error = nil }
    private func decode<T: Decodable>(_ type: T.Type, data: Data) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: data)
    }
    private func arguments(_ action: String) -> [String] {
        ["setup", action, "--profile", profile, "--region", region]
    }
    private func loadProfiles() async {
        guard !working else { return }
        working = true; progress = "Looking for local AWS profiles…"
        defer { working = false }
        do {
            let list = try decode(ProfileList.self, data: await bridge.execute(settings: model.settings, command: ["setup", "profiles"], timeout: 20))
            profiles = list.profiles; regions = list.regions
            ssoProfiles = list.ssoProfiles ?? []
            if profile.isEmpty, let current = list.currentProfile, profiles.contains(current) { profile = current }
            if !profiles.contains(profile) { profile = "" }
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    private func check() async {
        guard !working else { return }
        working = true; progress = "Checking your AWS account…"; review = nil; connected = false; error = nil
        defer { working = false }
        do {
            if useCredentials && credentialDraft.isReady {
                let imported = try decode(ImportedCredentials.self, data: await bridge.execute(settings: model.settings,
                    command: ["setup", "import-credentials", "--region", region], timeout: 60, input: try credentialDraft.input()))
                profile = imported.profile
                if !profiles.contains(profile) { profiles.append(profile) }
                credentialDraft = CredentialDraft()
                credentialNotice = imported.temporary
                    ? "Saved in macOS Keychain. Temporary credentials expire; paste a fresh set here when needed."
                    : "Saved in macOS Keychain. You can replace these credentials here when you rotate your keys."
            }
            review = try decode(ConnectionReview.self, data: await bridge.execute(settings: model.settings, command: arguments("check"), timeout: 240))
        } catch { self.error = error.localizedDescription }
    }
    private func signIn() async {
        guard !working else { return }
        working = true; progress = "Complete AWS sign-in in your browser…"; error = nil
        do { _ = try await bridge.execute(settings: model.settings, command: arguments("login"), timeout: 200) }
        catch { self.error = error.localizedDescription }
        working = false
        if error == nil { await check() }
    }
    private func connect() async {
        guard let review, !working else { return }
        working = true; progress = "Saving your connection…"; error = nil
        defer { working = false; model.configuring = false }
        do {
            let saved = try decode(ConnectionSaved.self, data: await bridge.execute(settings: model.settings,
                command: arguments("connect") + ["--account", review.accountId]))
            var settings = model.settings
            settings.configPath = saved.configPath; settings.demo = false
            settings.connectionMethod = profile.hasPrefix("cloudwake-keychain-") ? "credentials" : (ssoProfiles.contains(profile) ? "sso" : "profile")
            if let workspace {
                model.configuring = false
                _ = try await workspace.connect(settings: settings, accountID: review.accountId, name: accountName)
                connected = true
            } else {
                await model.save(settings)
                connected = model.settings == settings && model.error == nil
            }
            if !connected { error = model.error ?? "Could not save the connection. Try again." }
            else if let warning = saved.warning { error = "Connected for costs. Resource alerts: " + warning }
        } catch { self.error = error.localizedDescription }
    }
    private func install() async {
        guard let review, !working else { return }
        working = true; progress = "Installing resource notifications in AWS. This can take several minutes…"; error = nil
        do {
            _ = try decode(ConnectionSaved.self, data: await bridge.execute(settings: model.settings,
                command: arguments("install-events") + ["--account", review.accountId], timeout: 660))
        } catch { self.error = error.localizedDescription }
        working = false
        if error == nil { await check() }
    }
    private func consoleURL(_ feature: String) -> URL {
        let paths = ["costs": "costmanagement/home#/cost-explorer", "savings": "costmanagement/home#/cost-optimization-hub",
                     "history": "cloudtrailv2/home?region=\(region)#/events", "trail": "cloudtrailv2/home?region=\(region)#/trails", "events": "cloudformation/home?region=\(region)#/stacks"]
        return URL(string: "https://console.aws.amazon.com/" + (paths[feature] ?? "console/home"))!
    }
}
