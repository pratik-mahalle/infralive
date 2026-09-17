import AppKit
import SwiftUI

/// Shared vector geometry for the app icon, menu bar, and in-app brand.
enum CloudwakeArtwork {
    static var path: Path {
        var path = Path()
        path.move(to: CGPoint(x: 73, y: 69))
        path.addCurve(to: CGPoint(x: 90, y: 48), control1: CGPoint(x: 86, y: 69), control2: CGPoint(x: 92, y: 59))
        path.addCurve(to: CGPoint(x: 70, y: 34), control1: CGPoint(x: 88, y: 39), control2: CGPoint(x: 80, y: 33))
        path.addCurve(to: CGPoint(x: 45, y: 18), control1: CGPoint(x: 67, y: 21), control2: CGPoint(x: 57, y: 15))
        path.addCurve(to: CGPoint(x: 26, y: 39), control1: CGPoint(x: 34, y: 20), control2: CGPoint(x: 27, y: 29))
        path.addCurve(to: CGPoint(x: 9, y: 56), control1: CGPoint(x: 15, y: 38), control2: CGPoint(x: 8, y: 46))
        path.addCurve(to: CGPoint(x: 24, y: 69), control1: CGPoint(x: 9, y: 64), control2: CGPoint(x: 15, y: 69))
        for point in [(34.0, 69.0), (42.0, 51.0), (53.0, 80.0), (63.0, 60.0), (68.0, 69.0), (73.0, 69.0)] {
            path.addLine(to: CGPoint(x: point.0, y: point.1))
        }
        return path
    }

    static let menuImage: NSImage = {
        let image = NSImage(size: NSSize(width: 22, height: 18), flipped: true) { _ in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }
            context.scaleBy(x: 0.22, y: 0.22)
            context.translateBy(x: 0, y: -8)
            context.addPath(path.cgPath)
            context.setStrokeColor(NSColor.black.cgColor)
            context.setLineWidth(7)
            context.setLineCap(.round)
            context.setLineJoin(.round)
            context.strokePath()
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Cloudwake"
        return image
    }()
}

struct CloudwakeSymbol: Shape {
    func path(in rect: CGRect) -> Path {
        CloudwakeArtwork.path.applying(CGAffineTransform(scaleX: rect.width / 100, y: rect.height / 100)
            .concatenating(CGAffineTransform(translationX: rect.minX, y: rect.minY)))
    }
}

struct BrandMark: View {
    var size: CGFloat = 36

    var body: some View {
        CloudwakeSymbol()
            .stroke(style: StrokeStyle(lineWidth: size * 0.065, lineCap: .round, lineJoin: .round))
            .foregroundStyle(.primary)
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}
