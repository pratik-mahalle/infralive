// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "CostBar",
    platforms: [.macOS(.v13)],
    products: [.executable(name: "CostBar", targets: ["CostBar"])],
    targets: [
        .executableTarget(name: "CostBar"),
        .testTarget(name: "CostBarTests", dependencies: ["CostBar"], resources: [.copy("Fixtures")]),
    ]
)
