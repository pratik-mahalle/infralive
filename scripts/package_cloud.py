"""Bundle only application code and explicit SDK dependencies, never local config or data."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "dist" / "cloudpulse-monitor.zip"
target.parent.mkdir(exist_ok=True)
packages = [root / "src" / "aws_cost_agent"]
for name in ("boto3", "botocore", "s3transfer", "jmespath", "dateutil", "urllib3", "six"):
    spec = importlib.util.find_spec(name)
    packages.append(Path(spec.origin).parent if spec.submodule_search_locations else Path(spec.origin))
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for package in packages:
        files = package.rglob("*") if package.is_dir() else [package]
        for path in sorted(files):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                archive.write(path, str(path.relative_to(package.parent)))
print(
    json.dumps(
        {
            "path": str(target),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size,
        }
    )
)
