"""Package the local Mac build with a standalone Python; no credentials or account data."""

import argparse
import hashlib
import importlib.metadata
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-runtime", required=True, type=Path)
    args = parser.parse_args()
    runtime = args.python_runtime.resolve()
    if not (runtime / "bin/python3.12").is_file():
        parser.error("Expected a standalone Python 3.12 runtime directory")
    release = ROOT / "dist/release"
    target = release / "Cloudwake.app"
    if target.exists():
        shutil.rmtree(target)
    release.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "dist/Cloudwake.app", target, symlinks=True)
    resources = target / "Contents/Resources"
    agent = resources / "Agent"
    shutil.copytree(
        ROOT / "src/aws_cost_agent",
        agent / "src/aws_cost_agent",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    # Ship our collector as Python 3.12 bytecode, not readable source. Use legacy
    # adjacent .pyc files so imports still work after the source files are removed.
    # Bytecode is packaging, not an encryption or reverse-engineering guarantee.
    subprocess.run(
        [
            str(runtime / "bin/python3.12"),
            "-m",
            "compileall",
            "-q",
            "-b",
            "-s",
            str(agent / "src"),
            "-p",
            "Cloudwake",
            str(agent / "src"),
        ],
        check=True,
    )
    for source in (agent / "src").rglob("*.py"):
        if not source.with_suffix(".pyc").is_file():
            raise RuntimeError(f"Missing compiled collector module: {source.name}")
        source.unlink()
    (agent / "infra").mkdir()
    shutil.copy2(ROOT / "infra/events.json", agent / "infra/events.json")
    for name in ("LICENSE", "config.example.toml"):
        shutil.copy2(ROOT / name, agent / name)
    shutil.copy2(ROOT / "docs/downloads.md", agent / "README.md")
    shutil.copytree(
        runtime, resources / "Python", symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    packages = resources / "Python/lib/python3.12/site-packages"
    # Keep distribution metadata and licenses with each explicit runtime dependency.
    for name in (
        "boto3",
        "botocore",
        "s3transfer",
        "jmespath",
        "python-dateutil",
        "urllib3",
        "six",
        "keyring",
        "jaraco.classes",
        "jaraco.context",
        "jaraco.functools",
        "more-itertools",
    ):
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or ():
            relative = Path(file)
            if ".." in relative.parts or "__pycache__" in relative.parts or relative.suffix == ".pyc":
                continue
            source = Path(distribution.locate_file(file))
            if source.is_file():
                destination = packages / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    info = target / "Contents/Info.plist"
    metadata = plistlib.loads(info.read_bytes())
    metadata.pop("AgentProjectPath", None)
    info.write_bytes(plistlib.dumps(metadata))
    version = metadata["CFBundleShortVersionString"]
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(target)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(target)], check=True)
    subprocess.run([str(target / "Contents/MacOS/CostBar"), "--check-bundle"], check=True)
    subprocess.run(
        [
            str(resources / "Python/bin/python3.12"),
            "-B",
            "-s",
            str(ROOT / "scripts/check_macos_setup.py"),
            str(target),
        ],
        check=True,
    )
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(target)], check=True)
    archive = release / f"Cloudwake-{version}-macos-arm64.zip"
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(target), str(archive)], check=True
    )
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n")
    print(
        json.dumps(
            {"archive": str(archive), "sha256": checksum, "version": version, "bytes": archive.stat().st_size}
        )
    )


if __name__ == "__main__":
    main()
