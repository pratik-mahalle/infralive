import SwiftUI

/// A small, resolution-independent companion. No animation or remote artwork is required.
struct CloudMascot: View {
    var size: CGFloat = 72
    var sleepy = false

    var body: some View {
        ZStack {
            Ellipse().fill(Color.black.opacity(0.08)).frame(width: 62, height: 8).offset(y: 30)
            CloudBody().fill(LinearGradient(colors: [.white, Color(red: 0.82, green: 0.90, blue: 0.96)], startPoint: .topLeading, endPoint: .bottomTrailing))
                .overlay(CloudBody().stroke(.white.opacity(0.8), lineWidth: 1))
                .shadow(color: Color(red: 0.22, green: 0.39, blue: 0.47).opacity(0.18), radius: 3, y: 3)
            HStack(spacing: 15) {
                eye
                eye
            }.offset(x: 1, y: 3)
            HStack(spacing: 32) {
                Ellipse().fill(Color.pink.opacity(0.25))
                Ellipse().fill(Color.pink.opacity(0.25))
            }.frame(width: 53, height: 5).offset(y: 12)
            Path { p in
                p.move(to: CGPoint(x: 35, y: 44))
                p.addQuadCurve(to: CGPoint(x: 44, y: 44), control: CGPoint(x: 39.5, y: 50))
            }.stroke(Color(red: 0.20, green: 0.31, blue: 0.38), style: StrokeStyle(lineWidth: 1.8, lineCap: .round))
            HStack(spacing: 29) {
                Capsule().fill(Color(red: 0.85, green: 0.92, blue: 0.96))
                Capsule().fill(Color(red: 0.85, green: 0.92, blue: 0.96))
            }.frame(width: 53, height: 8).offset(y: 26)
        }
        .frame(width: 80, height: 72)
        .scaleEffect(size / 80)
        .frame(width: size, height: size * 0.9)
        .accessibilityHidden(true)
    }

    private var eye: some View {
        Capsule().fill(Color(red: 0.16, green: 0.27, blue: 0.34))
            .frame(width: 4, height: sleepy ? 2 : 7)
            .overlay(alignment: .topLeading) {
                if !sleepy { Circle().fill(.white).frame(width: 1.5, height: 1.5).padding(0.6) }
            }
    }
}

private struct CloudBody: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: 19, y: 58))
        p.addCurve(to: CGPoint(x: 12, y: 29), control1: CGPoint(x: 0, y: 57), control2: CGPoint(x: 0, y: 34))
        p.addCurve(to: CGPoint(x: 42, y: 17), control1: CGPoint(x: 12, y: 8), control2: CGPoint(x: 34, y: 3))
        p.addCurve(to: CGPoint(x: 66, y: 30), control1: CGPoint(x: 55, y: 7), control2: CGPoint(x: 70, y: 16))
        p.addCurve(to: CGPoint(x: 64, y: 58), control1: CGPoint(x: 84, y: 32), control2: CGPoint(x: 84, y: 57))
        p.closeSubpath()
        return p.applying(CGAffineTransform(scaleX: rect.width / 80, y: rect.height / 72))
    }
}

struct CloudCard: ViewModifier {
    @Environment(\.colorScheme) private var scheme
    func body(content: Content) -> some View {
        content.padding(14)
            .background(scheme == .dark ? Color.white.opacity(0.045) : Color.white.opacity(0.48), in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.primary.opacity(0.055), lineWidth: 1))
    }
}
