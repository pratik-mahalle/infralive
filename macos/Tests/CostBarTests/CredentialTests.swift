import Foundation
import Testing
@testable import CostBar

struct CredentialTests {
    @Test func manualInputAndClipboardHaveBoundedPayloads() throws {
        let draft = CredentialDraft(accessKey: "example-id", secretKey: "example-secret", sessionToken: "example-token")
        let json = try #require(JSONSerialization.jsonObject(with: draft.input()) as? [String: String])
        #expect(json["SecretAccessKey"] == "example-secret")
        #expect(json["SessionToken"] == "example-token")
        #expect(CredentialDraft(secretKey: "partial").hasInput)
        #expect(!CredentialDraft(secretKey: "partial").isReady)
        #expect(throws: (any Error).self) { try CredentialDraft(pasted: String(repeating: "x", count: 32769)).input() }
    }

    @Test func secretsUseStdinAndCannotAppearInArgumentsOrEnvironment() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("cloudwake-stdin-\(UUID())")
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("src/aws_cost_agent")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        try Data().write(to: source.appendingPathComponent("cli.py"))
        try Data().write(to: source.appendingPathComponent("__init__.py"))
        let script = """
        import os, sys
        value = sys.stdin.read()
        assert len(value) == 32768
        assert value not in str(sys.argv)
        assert value not in str(os.environ)
        print('Received through stdin')
        """
        try script.write(to: source.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)
        let settings = AgentSettings(projectPath: root.path, pythonPath: "/usr/bin/python3", configPath: "", demo: true)
        let output = try await AgentBridge().execute(settings: settings, command: ["setup", "import-credentials"],
                                                     timeout: 10, input: Data(String(repeating: "s", count: 32768).utf8))
        #expect(String(decoding: output, as: UTF8.self) == "Received through stdin\n")
        try "import sys; sys.exit(2)".write(to: source.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)
        await #expect(throws: (any Error).self) {
            try await AgentBridge().execute(settings: settings, command: ["setup", "import-credentials"],
                                             timeout: 1, input: Data(repeating: 115, count: 32768))
        }
        try "import time; time.sleep(5)".write(to: source.appendingPathComponent("__main__.py"), atomically: true, encoding: .utf8)
        await #expect(throws: (any Error).self) {
            try await AgentBridge().execute(settings: settings, command: ["setup", "import-credentials"],
                                             timeout: 0.2, input: Data(repeating: 115, count: 32768))
        }
    }

    @Test func olderSettingsRemainDecodable() throws {
        let data = Data(#"{"projectPath":"/example","pythonPath":"/python","configPath":"/config","demo":false}"#.utf8)
        let settings = try JSONDecoder().decode(AgentSettings.self, from: data)
        #expect(settings.connectionMethod == nil)
    }
}
