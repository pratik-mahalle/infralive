import SwiftUI

struct AccountPicker: View {
    @ObservedObject var workspace: AccountWorkspace
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "server.rack").foregroundStyle(.secondary).accessibilityHidden(true)
            Picker("AWS account", selection: Binding(get: { workspace.selectedID }, set: { workspace.select($0) })) {
                ForEach(workspace.accounts) { account in
                    Text(account.label + (workspace.model(for: account.id)?.needsSignIn == true ? " · Sign-in required" : ""))
                        .tag(account.id)
                }
            }
            .labelsHidden().pickerStyle(.menu).frame(maxWidth: .infinity)
        }.padding(.horizontal, 10).padding(.vertical, 6)
        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10))
        .disabled(workspace.isConfiguring)
        .help("Switch accounts. Other accounts keep monitoring.")
    }
}

struct AccountSettings: View {
    @ObservedObject var workspace: AccountWorkspace
    @State private var removal: SavedAccount?
    @State private var name = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Your accounts", systemImage: "person.2").font(.headline)
            AccountPicker(workspace: workspace)
            ForEach(workspace.accounts.filter { !$0.settings.demo }) { account in
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(account.title).font(.callout.weight(.medium))
                        Text(account.accountID ?? "Waiting for account data").font(.caption.monospaced()).foregroundStyle(.secondary)
                        if let model = workspace.model(for: account.id) {
                            Text(model.needsSignIn ? "Sign-in required" : (model.isMonitoring ? "Monitoring" : "Paused"))
                                .font(.caption).foregroundStyle(model.needsSignIn ? .orange : .secondary)
                            if let error = model.error { Text(error).font(.caption).foregroundStyle(.orange).lineLimit(2) }
                        }
                    }
                    Spacer()
                    if let model = workspace.model(for: account.id) {
                        if model.ownsWorker {
                            Button("Pause") { model.stopWorker() }.controlSize(.small)
                        } else if !model.isMonitoring && !model.usesCloudMonitoring && !model.needsSignIn {
                            Button("Start") { Task { await model.startWorker() } }.controlSize(.small).disabled(model.busy)
                        }
                        Button("Remove…") { removal = account }.controlSize(.small)
                            .disabled(model.busy || model.asking || model.configuring)
                    }
                }
            }
            if !workspace.selectedModel.settings.demo {
                HStack {
                    TextField("Account name, e.g. Production", text: $name).textFieldStyle(.roundedBorder)
                    Button("Rename") { workspace.rename(workspace.selectedID, name: name) }
                        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            Text("Every account has its own spending, activity and inbox. Switching views keeps the other monitors running. Add another account below.")
                .font(.caption).foregroundStyle(.secondary)
            if let error = workspace.storageError { Text(error).font(.caption).foregroundStyle(.red) }
        }
        .onAppear { name = workspace.accounts.first(where: { $0.id == workspace.selectedID })?.name ?? "" }
        .onChange(of: workspace.selectedID) { id in name = workspace.accounts.first(where: { $0.id == id })?.name ?? "" }
        .alert("Remove this account from Cloudwake?", isPresented: Binding(get: { removal != nil }, set: { if !$0 { removal = nil } })) {
            Button("Cancel", role: .cancel) { removal = nil }
            Button("Remove account", role: .destructive) {
                if let removal { workspace.remove(removal.id) }
                removal = nil
            }
        } message: {
            Text("\(removal?.title ?? "This account") will stop local monitoring. Saved data and credentials stay on this Mac. Any monitor deployed in AWS keeps running.")
        }
    }
}
