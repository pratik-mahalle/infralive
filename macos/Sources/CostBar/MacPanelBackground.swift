import AppKit
import SwiftUI

/// macOS composites the desktop and windows behind the panel; no wallpaper file or screenshot is read.
struct MacPanelBackground: View {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        Group {
            if reduceTransparency {
                Color(nsColor: .windowBackgroundColor)
            } else {
                DesktopMaterial()
            }
        }.ignoresSafeArea().allowsHitTesting(false).accessibilityHidden(true)
    }
}

private struct DesktopMaterial: NSViewRepresentable {
    func makeNSView(context: Context) -> PanelEffectView {
        let view = PanelEffectView()
        view.material = .popover
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ view: PanelEffectView, context: Context) { }
}

private final class PanelEffectView: NSVisualEffectView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        // A solid hosting window would otherwise hide the desktop material.
        window?.isOpaque = false
        window?.backgroundColor = .clear
    }
}
