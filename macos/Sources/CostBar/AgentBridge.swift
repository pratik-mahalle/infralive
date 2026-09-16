import Foundation

enum BridgeError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let message): return message }
    }
}

struct AgentSettings: Codable, Equatable {
    var projectPath: String
    var pythonPath: String
    var configPath: String
    var demo: Bool

    static var initial: AgentSettings {
        let root = Bundle.main.object(forInfoDictionaryKey: "AgentProjectPath") as? String
            ?? ProcessInfo.processInfo.environment["COST_AGENT_PROJECT"]
            ?? FileManager.default.currentDirectoryPath
        return AgentSettings(projectPath: root, pythonPath: root + "/.venv/bin/python",
                             configPath: root + "/config.toml", demo: true)
    }

    func makeProcess(_ command: [String]) throws -> Process {
        guard FileManager.default.fileExists(atPath: projectPath + "/src/aws_cost_agent/cli.py") else {
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
        process.currentDirectoryURL = URL(fileURLWithPath: projectPath)
        // Argument arrays, never a shell command. Paths and questions are literal arguments.
        process.arguments = ["-m", "aws_cost_agent"] + (setup ? [] : (demo ? ["--demo"] : ["--config", configPath])) + command
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = projectPath + "/src"
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment
        return process
    }
}

/// Serial, off-main subprocess execution. Output uses temporary files to avoid pipe-buffer deadlocks.
actor AgentBridge {
    func execute(settings: AgentSettings, command: [String], timeout: TimeInterval = 90) throws -> Data {
        let process = try settings.makeProcess(command)
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
            throw BridgeError.message(String((detail?.isEmpty == false ? detail! : "The agent command failed.").suffix(1800)))
        }
        return try Data(contentsOf: output)
    }
}
