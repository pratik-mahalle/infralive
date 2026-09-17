import Combine
import Foundation

struct SavedAccount: Codable, Identifiable {
    var id: String
    var name: String
    var accountID: String?
    var settings: AgentSettings
    var monitoringRequested: Bool

    var title: String { settings.demo ? "Demo" : (name.isEmpty ? (accountID ?? "AWS account") : name) }
    var label: String { title + (accountID != nil && title != accountID ? " · " + accountID! : "") }
}

private struct SavedWorkspace: Codable {
    var accounts: [SavedAccount]
    var selectedID: String
}

/// Owns a separate polling loop, worker, inbox and authentication state for every connection.
@MainActor
final class AccountWorkspace: ObservableObject {
    @Published private(set) var accounts: [SavedAccount] = []
    @Published private(set) var selectedID = ""
    @Published private(set) var storageError: String?
    private var models: [String: AgentModel] = [:]
    private var subscriptions: [String: Set<AnyCancellable>] = [:]
    private let defaults: UserDefaults
    private let start: Bool
    private let makeBridge: () -> any AgentExecuting
    let notifier = DesktopNotifier()
    private let key = "Cloudwake.accounts.v1"

    init(defaults: UserDefaults = .standard, start: Bool = true,
         initialSettings: AgentSettings? = nil, makeBridge: @escaping () -> any AgentExecuting = { AgentBridge() }) {
        self.defaults = defaults
        self.start = start
        self.makeBridge = makeBridge
        if let data = defaults.data(forKey: key) {
            do {
                let saved = try JSONDecoder().decode(SavedWorkspace.self, from: data)
                guard !saved.accounts.isEmpty, Set(saved.accounts.map(\.id)).count == saved.accounts.count else {
                    throw BridgeError.message("Invalid saved account list")
                }
                accounts = saved.accounts
                selectedID = saved.selectedID
            } catch {
                storageError = "Saved accounts could not be loaded. Your connection files are unchanged."
            }
        }
        if accounts.isEmpty {
            let legacy = defaults.data(forKey: "CostBar.settings.v1")
                .flatMap { try? JSONDecoder().decode(AgentSettings.self, from: $0) }
            let settings = initialSettings ?? legacy ?? .initial
            let account = SavedAccount(id: UUID().uuidString, name: settings.demo ? "Demo" : "Existing account",
                                       settings: settings, monitoringRequested: false)
            accounts = [account]
            selectedID = account.id
        }
        if !accounts.contains(where: { $0.id == selectedID }) { selectedID = accounts[0].id }
        for account in accounts { attach(account) }
        persist()
    }

    var selectedModel: AgentModel { models[selectedID]! }
    var realAccountCount: Int { accounts.filter { !$0.settings.demo }.count }
    var isConfiguring: Bool { models.values.contains(where: \.configuring) }
    func model(for id: String) -> AgentModel? { models[id] }

    func select(_ id: String) {
        guard !isConfiguring, models[id] != nil else { return }
        selectedID = id
        persist()
    }

    /// Called only after setup has verified the account identity and written its isolated configuration.
    @discardableResult
    func connect(settings: AgentSettings, accountID: String, name: String) async throws -> String {
        guard storageError == nil else { throw BridgeError.message(storageError!) }
        guard !settings.demo, accountID.utf8.count == 12, accountID.utf8.allSatisfy({ (48...57).contains($0) }) else {
            throw BridgeError.message("Check an AWS account before adding it.")
        }
        _ = try settings.makeProcess(["status"])
        if let existing = accounts.first(where: {
            !$0.settings.demo && ($0.accountID == accountID || models[$0.id]?.status?.snapshot?.accountId == accountID || $0.settings.configPath == settings.configPath)
        }), let model = models[existing.id] {
            // One connection per AWS account prevents duplicate workers and duplicate alerts.
            guard !model.busy && !model.asking else {
                throw BridgeError.message("This account is busy. Wait for its current task before reconnecting.")
            }
            let resume = model.monitoringRequested
            if model.ownsWorker {
                // A running SDK session can retain old pasted credentials. Restart only this worker.
                model.stopWorker()
                for _ in 0..<100 {
                    if !model.ownsWorker && !model.busy { break }
                    try await Task.sleep(nanoseconds: 50_000_000)
                }
                guard !model.ownsWorker && !model.busy else {
                    throw BridgeError.message("The account is still stopping. Try reconnecting once it is paused.")
                }
            }
            if model.settings != settings {
                await model.save(settings)
                guard model.settings == settings else { throw BridgeError.message(model.error ?? "Unable to update connection") }
            }
            rename(existing.id, name: name)
            if let index = accounts.firstIndex(where: { $0.id == existing.id }) {
                accounts[index].accountID = accountID
                model.accountLabel = notificationLabel(accounts[index])
            }
            if model.needsSignIn { await model.retryConnection() }
            if resume { await model.startWorker() }
            selectedID = existing.id
            persist()
            return existing.id
        }
        let entry = SavedAccount(id: UUID().uuidString, name: String(name.trimmingCharacters(in: .whitespacesAndNewlines).prefix(60)),
                                 accountID: accountID, settings: settings, monitoringRequested: true)
        accounts.append(entry)
        attach(entry)
        selectedID = entry.id
        persist()
        return entry.id
    }

    func rename(_ id: String, name: String) {
        guard let index = accounts.firstIndex(where: { $0.id == id }) else { return }
        let name = String(name.trimmingCharacters(in: .whitespacesAndNewlines).prefix(60))
        if !name.isEmpty { accounts[index].name = name }
        models[id]?.accountLabel = notificationLabel(accounts[index])
        persist()
    }

    func remove(_ id: String) {
        guard let model = models[id], !model.busy, !model.asking, !model.configuring else { return }
        model.shutdown()
        subscriptions.removeValue(forKey: id)
        models.removeValue(forKey: id)
        accounts.removeAll { $0.id == id }
        if accounts.isEmpty {
            var settings = model.settings
            settings.demo = true
            let demo = SavedAccount(id: UUID().uuidString, name: "Demo", settings: settings, monitoringRequested: false)
            accounts.append(demo)
            attach(demo)
        }
        if selectedID == id { selectedID = accounts[0].id }
        persist()
    }

    func shutdown() { models.values.forEach { $0.shutdown() } }

    private func attach(_ entry: SavedAccount) {
        let model = AgentModel(start: start, bridge: makeBridge(), initialSettings: entry.settings,
                               monitoringRequested: entry.monitoringRequested, notifier: notifier)
        model.accountLabel = notificationLabel(entry)
        models[entry.id] = model
        var tokens = Set<AnyCancellable>()
        model.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }.store(in: &tokens)
        model.$settings.sink { [weak self] settings in
            guard let self, let index = self.accounts.firstIndex(where: { $0.id == entry.id }) else { return }
            self.accounts[index].settings = settings
            self.persist()
        }.store(in: &tokens)
        model.$monitoringRequested.sink { [weak self] value in
            guard let self, let index = self.accounts.firstIndex(where: { $0.id == entry.id }) else { return }
            self.accounts[index].monitoringRequested = value
            self.persist()
        }.store(in: &tokens)
        model.$status.sink { [weak self] value in
            guard let self, let accountID = value?.snapshot?.accountId, value?.demo == false,
                  let index = self.accounts.firstIndex(where: { $0.id == entry.id }) else { return }
            self.accounts[index].accountID = accountID
            self.models[entry.id]?.accountLabel = self.notificationLabel(self.accounts[index])
            self.persist()
        }.store(in: &tokens)
        subscriptions[entry.id] = tokens
    }

    private func persist() {
        // Never overwrite an unreadable registry with a fallback demo connection.
        guard storageError == nil else { return }
        do { defaults.set(try JSONEncoder().encode(SavedWorkspace(accounts: accounts, selectedID: selectedID)), forKey: key) }
        catch { storageError = "Unable to save your account list: " + error.localizedDescription }
    }

    private func notificationLabel(_ account: SavedAccount) -> String {
        account.label
    }
}
