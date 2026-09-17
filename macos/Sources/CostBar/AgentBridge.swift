import Darwin
import Foundation

enum BridgeError: LocalizedError {
    case message(String)
    case authenticationRequired

    var requiresSignIn: Bool {
        if case .authenticationRequired = self { return true }
        return false
    }
    var errorDescription: String? {
        switch self {
        case .message(let message): return message
        case .authenticationRequired: return "Your AWS session expired. Sign in again to reconnect."
        }
    }
    static func processFailure(_ detail: String) -> BridgeError {
        let markers = ["AWS sign-in required:", "TokenRetrievalError", "SSOTokenLoadError",
                       "UnauthorizedSSOTokenError", "ExpiredToken", "InvalidGrantException"]
        if markers.contains(where: { detail.contains($0) }) { return .authenticationRequired }
        // SDK diagnostics can contain a full traceback. Show only the final actionable line.
        let lastLine = detail.split(separator: "\n").last.map(String.init) ?? "The agent command failed."
        return .message(String(lastLine.prefix(350)))
    }
}

struct AgentSettings: Codable, Equatable {
    var projectPath: String
    var pythonPath: String
    var configPath: String
    var demo: Bool
    var dataPath: String? = nil
    var connectionMethod: String? = nil

    var workingDirectory: String { dataPath ?? projectPath }

    func relocatedToCurrentBundle() -> AgentSettings {
        var result = self
        if dataPath != nil && projectPath.hasSuffix(".app/Contents/Resources/Agent"),
           Self.initial.dataPath != nil {
            result.projectPath = Self.initial.projectPath
            result.pythonPath = Self.initial.pythonPath
        }
        return result
    }

    static func bundled(resources: URL, support: URL) -> AgentSettings {
        AgentSettings(projectPath: resources.appendingPathComponent("Agent").path,
                      pythonPath: resources.appendingPathComponent("Python/bin/python3.12").path,
                      configPath: support.appendingPathComponent("config.toml").path,
                      demo: true, dataPath: support.path)
    }

    static var initial: AgentSettings {
        if let resources = Bundle.main.resourceURL,
           hasAgent(at: resources.appendingPathComponent("Agent").path) {
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Cloudwake")
            return bundled(resources: resources, support: support)
        }
        let root = Bundle.main.object(forInfoDictionaryKey: "AgentProjectPath") as? String
            ?? ProcessInfo.processInfo.environment["COST_AGENT_PROJECT"]
            ?? FileManager.default.currentDirectoryPath
        return AgentSettings(projectPath: root, pythonPath: root + "/.venv/bin/python",
                             configPath: root + "/config.toml", demo: true)
    }

    static func hasAgent(at root: String) -> Bool {
        ["cli.py", "cli.pyc"].contains {
            FileManager.default.fileExists(atPath: root + "/src/aws_cost_agent/" + $0)
        }
    }

    func makeProcess(_ command: [String]) throws -> Process {
        guard Self.hasAgent(at: projectPath) else {
            throw BridgeError.message("Choose the aws-cost-agent project folder in Settings.")
        }
        guard FileManager.default.isExecutableFile(atPath: pythonPath) else {
            throw BridgeError.message("Python is missing. Choose the project's .venv/bin/python in Settings.")
        }
        let setup = command.first == "setup"
        guard setup || demo || FileManager.default.fileExists(atPath: configPath) else {
            throw BridgeError.message("AWS configuration is missing. Copy config.example.toml to config.toml and add your account details.")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        try FileManager.default.createDirectory(atPath: workingDirectory, withIntermediateDirectories: true)
        process.currentDirectoryURL = URL(fileURLWithPath: workingDirectory)
        // Argument arrays, never a shell command. Paths and questions are literal arguments.
        let configuration = !demo && FileManager.default.fileExists(atPath: configPath) ? ["--config", configPath] : []
        process.arguments = ["-m", "aws_cost_agent"] + (setup ? configuration : (demo ? ["--demo"] : ["--config", configPath])) + command
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = projectPath + "/src"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONNOUSERSITE"] = "1"
        process.environment = environment
        return process
    }
}

/// Serial, off-main subprocess execution. Output uses temporary files to avoid pipe-buffer deadlocks.
protocol AgentExecuting: Sendable {
    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval) async throws -> Data
}

extension AgentExecuting {
    func execute(settings: AgentSettings, command: [String]) async throws -> Data {
        try await execute(settings: settings, command: command, timeout: 90)
    }
}

actor AgentBridge: AgentExecuting {
    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval = 90) throws -> Data {
        try execute(settings: settings, command: command, timeout: timeout, input: nil)
    }

    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval = 90, input: Data?) throws -> Data {
        guard (input?.count ?? 0) <= 32768 else { throw BridgeError.message("Credential input is too large.") }
        let process = try settings.makeProcess(command)
        // Credentials travel through an anonymous pipe, never argv, environment, or temporary files.
        let inputPipe = Pipe()
        // A helper that exits before reading must not terminate the app with SIGPIPE.
        _ = fcntl(inputPipe.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        process.standardInput = inputPipe
        defer { try? inputPipe.fileHandleForReading.close(); try? inputPipe.fileHandleForWriting.close() }
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: temporary, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let output = temporary.appendingPathComponent("stdout")
        let errors = temporary.appendingPathComponent("stderr")
        FileManager.default.createFile(atPath: output.path, contents: nil)
        FileManager.default.createFile(atPath: errors.path, contents: nil)
        let outHandle = try FileHandle(forWritingTo: output)
        let errHandle = try FileHandle(forWritingTo: errors)
        defer { try? outHandle.close(); try? errHandle.close() }
        process.standardOutput = outHandle
        process.standardError = errHandle
        try process.run()
        try inputPipe.fileHandleForReading.close()
        let inputHandle = inputPipe.fileHandleForWriting
        DispatchQueue.global(qos: .userInitiated).async {
            if let input { try? inputHandle.write(contentsOf: input) }
            try? inputHandle.close()
        }
        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning {
            if Date() > deadline || Task.isCancelled {
                process.terminate()
                Thread.sleep(forTimeInterval: 0.2)
                if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                process.waitUntilExit()
                throw BridgeError.message("The agent took too long to respond. Check AWS access and try again.")
            }
            Thread.sleep(forTimeInterval: 0.05)
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = (try? String(contentsOf: errors, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
            throw BridgeError.processFailure(detail ?? "")
        }
        return try Data(contentsOf: output)
    }
}
