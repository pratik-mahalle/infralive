import AppKit
import SwiftUI

struct CredentialDraft: Equatable {
    var accessKey = ""
    var secretKey = ""
    var sessionToken = ""
    var pasted = ""

    var isReady: Bool { !pasted.isEmpty || (!accessKey.isEmpty && !secretKey.isEmpty) }
    var hasInput: Bool { !pasted.isEmpty || !accessKey.isEmpty || !secretKey.isEmpty || !sessionToken.isEmpty }

    func input() throws -> Data {
        let data = pasted.isEmpty
            ? try JSONSerialization.data(withJSONObject: ["AccessKeyId": accessKey, "SecretAccessKey": secretKey, "SessionToken": sessionToken])
            : Data(pasted.utf8)
        guard data.count <= 32768 else { throw BridgeError.message("Credentials are too long. Copy only the AWS credential values.") }
        return data
    }
}

struct CredentialEntry: View {
    @Binding var draft: CredentialDraft
    @State private var pasteError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Button("Paste from clipboard") {
                    guard let text = NSPasteboard.general.string(forType: .string), !text.isEmpty, text.utf8.count <= 32768 else {
                        pasteError = "Copy the AWS credentials first (up to 32 KB)."
                        return
                    }
                    draft = CredentialDraft(pasted: text)
                    pasteError = nil
                }
                if !draft.pasted.isEmpty {
                    Label("Ready to check", systemImage: "checkmark.circle").font(.caption).foregroundStyle(.secondary)
                    Button("Clear") { draft = CredentialDraft() }
                }
            }
            if draft.pasted.isEmpty {
                SecureField("Access key ID", text: $draft.accessKey)
                SecureField("Secret access key", text: $draft.secretKey)
                SecureField("Session token (for temporary credentials)", text: $draft.sessionToken)
            }
            Text("Paste AWS export lines, credential JSON, or enter keys above. Check account verifies access and saves credentials in macOS Keychain. Nothing pasted is executed.")
                .font(.caption).foregroundStyle(.secondary)
            Text("Temporary credentials need all three values and must be replaced when they expire.")
                .font(.caption).foregroundStyle(.secondary)
            if let pasteError { Text(pasteError).font(.caption).foregroundStyle(.red) }
        }.textFieldStyle(.roundedBorder)
    }
}
