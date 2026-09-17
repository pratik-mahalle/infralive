import AppKit
import SwiftUI

struct AlertDestination: Codable, Equatable {
    let connectionID: String
    let feedID: String
    let sequences: [Int]

    var valid: Bool { !connectionID.isEmpty && !feedID.isEmpty && !sequences.isEmpty && sequences.allSatisfy { $0 > 0 } }
}

struct CompanionNotice: Identifiable {
    let id: String
    let heading: String
    let detail: String
    let account: String
    let destination: AlertDestination?

    static func heading(kind: String, count: Int) -> String {
        if count > 1 { return "A few things need a look." }
        switch kind {
        case "event": return "Something new in your cloud."
        case "idle": return "This might be sitting idle."
        case "spend": return "Your spending picked up."
        case "budget": return "Let's check that forecast."
        default: return "A little heads-up."
        }
    }

    static let preview = CompanionNotice(id: "preview", heading: "This might be sitting idle.",
        detail: "An unused resource could save you about $40/month.", account: "Preview · Example AWS account", destination: nil)
}

struct CompanionBubble: View {
    let notice: CompanionNotice
    var busy = false
    var error: String? = nil
    let review: () -> Void
    let later: () -> Void
    let dismiss: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            CloudMascot(size: 80).padding(.top, 22).padding(.trailing, -3)
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(notice.account).font(.system(size: 10, weight: .medium)).foregroundStyle(.secondary).lineLimit(1)
                    Spacer(minLength: 4)
                    Button(action: dismiss) { Image(systemName: "xmark").font(.system(size: 9, weight: .semibold)).frame(width: 20, height: 20) }
                        .buttonStyle(.plain).foregroundStyle(.secondary).help("Dismiss; keep in Inbox").accessibilityLabel("Dismiss alert").disabled(busy)
                }
                Text(notice.heading).font(.system(size: 16, weight: .semibold, design: .rounded)).fixedSize(horizontal: false, vertical: true)
                Text(notice.detail).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(3).fixedSize(horizontal: false, vertical: true)
                if let error { Text(error).font(.caption2).foregroundStyle(.orange).lineLimit(3) }
                HStack(spacing: 12) {
                    Button(notice.destination == nil ? "Got it" : "Review", action: review).buttonStyle(.borderedProminent).tint(Color(red: 0.24, green: 0.42, blue: 0.48))
                    if notice.destination != nil {
                        Button("In 1 hour", action: later).buttonStyle(.plain).foregroundStyle(.secondary).help("Snooze these alerts in this account's inbox for one hour")
                    }
                    if busy { ProgressView().controlSize(.small) }
                    Spacer(minLength: 0)
                }.controlSize(.small).disabled(busy).padding(.top, 2)
            }
            .padding(16).frame(width: 294, alignment: .leading)
            .background(scheme == .dark ? Color(red: 0.16, green: 0.20, blue: 0.23) : Color(red: 0.97, green: 0.98, blue: 0.96), in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.primary.opacity(0.07), lineWidth: 1))
            .overlay(alignment: .topLeading) {
                UnevenBubbleTail().fill(scheme == .dark ? Color(red: 0.16, green: 0.20, blue: 0.23) : Color(red: 0.97, green: 0.98, blue: 0.96))
                    .frame(width: 14, height: 17).offset(x: -12, y: 34)
            }
        }.padding(16)
            .shadow(color: .black.opacity(scheme == .dark ? 0.22 : 0.12), radius: 10, y: 4)
    }
}

private struct UnevenBubbleTail: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.maxX, y: 0))
        p.addQuadCurve(to: CGPoint(x: 0, y: 0), control: CGPoint(x: r.midX, y: r.midY))
        p.addQuadCurve(to: CGPoint(x: r.maxX, y: r.maxY), control: CGPoint(x: 0, y: r.maxY))
        p.closeSubpath()
        return p
    }
}

/// Presents only from foreground delivery or a deliberate notification click/preview.
@MainActor
final class CompanionPresenter: ObservableObject {
    @Published private(set) var notice: CompanionNotice?
    @Published private(set) var busy = false
    @Published private(set) var error: String?
    var review: ((AlertDestination) -> Void)?
    var snooze: ((AlertDestination) async throws -> Void)?
    private var panel: NSPanel?
    private var queue: [CompanionNotice] = []

    func show(_ item: CompanionNotice) {
        if notice != nil && panel?.isVisible == false && !busy {
            queue.removeAll()
            notice = nil
            panel = nil
        }
        guard item.id != notice?.id, !queue.contains(where: { $0.id == item.id }) else { return }
        guard notice == nil else {
            // All alerts remain in Notification Center and Inbox, even during bursts.
            if queue.count < 5 { queue.append(item) }
            return
        }
        notice = item
        error = nil
        let host = NSHostingView(rootView: CompanionPanelContent(presenter: self))
        let frame = (NSApp.keyWindow?.screen ?? NSScreen.main)?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1000, height: 800)
        let panel = CompanionPanel(contentRect: NSRect(x: frame.maxX - 432, y: frame.maxY - 300, width: 420, height: 284), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.hidesOnDeactivate = true
        panel.isMovableByWindowBackground = true
        panel.contentView = host
        self.panel = panel
        panel.orderFront(nil)
    }

    func dismiss() {
        guard !busy else { return }
        panel?.orderOut(nil)
        panel = nil
        notice = nil
        error = nil
        if !queue.isEmpty { show(queue.removeFirst()) }
    }

    func clear() {
        queue.removeAll()
        if !busy { dismiss() }
    }

    func reviewCurrent() {
        guard !busy else { return }
        if let destination = notice?.destination { review?(destination) }
        dismiss()
    }

    func snoozeCurrent() async {
        guard !busy, let destination = notice?.destination, let snooze else { return }
        busy = true
        error = nil
        do {
            try await snooze(destination)
            busy = false
            dismiss()
        } catch {
            self.error = error.localizedDescription
            busy = false
        }
    }
}

private final class CompanionPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
    override func cancelOperation(_ sender: Any?) { orderOut(nil) }
}

private struct CompanionPanelContent: View {
    @ObservedObject var presenter: CompanionPresenter
    var body: some View {
        if let notice = presenter.notice {
            CompanionBubble(notice: notice, busy: presenter.busy, error: presenter.error,
                review: { presenter.reviewCurrent() }, later: { Task { await presenter.snoozeCurrent() } }, dismiss: { presenter.dismiss() })
        }
    }
}
