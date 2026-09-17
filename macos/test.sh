#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$PROJECT_DIR/macos/.build"
mkdir -p "$BUILD_DIR/module-cache" "$BUILD_DIR/clang-cache" "$BUILD_DIR/package-cache"
SWIFT_DEVELOPER_PATH="$(xcode-select -p)"
export SWIFTPM_MODULECACHE_OVERRIDE="$BUILD_DIR/module-cache"
export CLANG_MODULE_CACHE_PATH="$BUILD_DIR/clang-cache"
# Keep this array nonempty: macOS Bash 3.2 rejects an empty array under nounset.
SWIFT_TEST_FLAGS=(--disable-xctest)

# Standalone Command Line Tools ship Swift Testing but don't add its framework/rpaths.
FRAMEWORK_DIR="$SWIFT_DEVELOPER_PATH/Library/Developer/Frameworks"
if [[ -d "$FRAMEWORK_DIR/Testing.framework" ]]; then
  SWIFT_TEST_FLAGS+=(-Xswiftc -F -Xswiftc "$FRAMEWORK_DIR"
    -Xlinker -F -Xlinker "$FRAMEWORK_DIR"
    -Xlinker -rpath -Xlinker "$FRAMEWORK_DIR"
    -Xlinker -rpath -Xlinker "$SWIFT_DEVELOPER_PATH/Library/Developer/usr/lib")
fi
swift test --package-path "$PROJECT_DIR/macos" --scratch-path "$BUILD_DIR" \
  --cache-path "$BUILD_DIR/package-cache" --config-path "$BUILD_DIR/config" \
  --security-path "$BUILD_DIR/security" --disable-sandbox "${SWIFT_TEST_FLAGS[@]}"
