#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/macos/.build"
APP_DIR="$PROJECT_DIR/dist/Cloudwake.app"
mkdir -p "$BUILD_DIR/module-cache" "$BUILD_DIR/clang-cache" "$BUILD_DIR/package-cache"

export SWIFTPM_MODULECACHE_OVERRIDE="$BUILD_DIR/module-cache"
export CLANG_MODULE_CACHE_PATH="$BUILD_DIR/clang-cache"
swift build --package-path "$PROJECT_DIR/macos" --scratch-path "$BUILD_DIR" \
  --cache-path "$BUILD_DIR/package-cache" --config-path "$BUILD_DIR/config" \
  --security-path "$BUILD_DIR/security" --disable-sandbox --configuration release

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$BUILD_DIR/release/CostBar" "$APP_DIR/Contents/MacOS/CostBar"
chmod +x "$APP_DIR/Contents/MacOS/CostBar"

python3 - "$APP_DIR/Contents/Info.plist" "$PROJECT_DIR" <<'PY'
import plistlib
import sys

with open(sys.argv[1], "wb") as file:
    plistlib.dump({
        "CFBundleName": "Cloudwake",
        "CFBundleDisplayName": "Cloudwake",
        "CFBundleIdentifier": "dev.aws-cost-agent.CostBar",
        "CFBundleExecutable": "CostBar",
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "Cloudwake",
        "CFBundleShortVersionString": "0.3.2",
        "CFBundleVersion": "5",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "AgentProjectPath": sys.argv[2],
    }, file)
PY

swiftc "$PROJECT_DIR/macos/Sources/CostBar/BrandMark.swift" "$PROJECT_DIR/macos/IconArtwork.swift" -o "$BUILD_DIR/render-icon"
"$BUILD_DIR/render-icon" "$BUILD_DIR/Cloudwake.iconset"
iconutil -c icns "$BUILD_DIR/Cloudwake.iconset" -o "$APP_DIR/Contents/Resources/Cloudwake.icns"
cp "$BUILD_DIR/Cloudwake.iconset/icon_512x512@2x.png" "$PROJECT_DIR/macos/Assets/Cloudwake.png"

# Ad-hoc signature for local use. Distribution requires a Developer ID and notarization.
codesign --force --sign - "$APP_DIR"
printf '\nBuilt: %s\nOpen with: open "%s"\n' "$APP_DIR" "$APP_DIR"
