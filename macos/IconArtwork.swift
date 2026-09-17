import AppKit
import SwiftUI

/// Renders the shared vector mark at native icon resolutions; no external asset tools.
@main
enum IconArtwork {
    static func main() throws {
        let destination = CommandLine.arguments[1]
        try FileManager.default.createDirectory(atPath: destination, withIntermediateDirectories: true)
        for base in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let suffix = scale == 2 ? "@2x" : ""
                try icon(base * scale).write(to: URL(fileURLWithPath: destination + "/icon_\(base)x\(base)\(suffix).png"))
            }
        }
    }

    static func icon(_ size: Int) throws -> Data {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let context = NSGraphicsContext.current!.cgContext
        let s = CGFloat(size)
        context.translateBy(x: 0, y: s)
        context.scaleBy(x: s / 1024, y: -s / 1024)
        let tile = CGPath(roundedRect: CGRect(x: 64, y: 64, width: 896, height: 896),
                          cornerWidth: 204, cornerHeight: 204, transform: nil)
        context.addPath(tile)
        context.setFillColor(NSColor(srgbRed: 15/255, green: 29/255, blue: 40/255, alpha: 1).cgColor)
        context.fillPath()
        context.addPath(tile)
        context.setStrokeColor(NSColor(srgbRed: 40/255, green: 61/255, blue: 72/255, alpha: 1).cgColor)
        context.setLineWidth(2)
        context.strokePath()
        context.translateBy(x: 152, y: 152)
        context.scaleBy(x: 7.2, y: 7.2)
        context.addPath(CloudwakeArtwork.path.cgPath)
        context.setStrokeColor(NSColor(srgbRed: 113/255, green: 239/255, blue: 197/255, alpha: 1).cgColor)
        context.setLineWidth(6.5)
        context.setLineCap(.round)
        context.setLineJoin(.round)
        context.strokePath()
        return rep.representation(using: .png, properties: [:])!
    }
}
