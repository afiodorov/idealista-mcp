#!/usr/bin/env python3
"""Test and cross-compile this checkout for ARM64 Lambda using a pinned Go image."""

import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
GO_IMAGE = "golang:1.26.1-alpine@sha256:2389ebfa5b7f43eeafbd6be0c3700cc46690ef842ad962f6c5bd6be49ed82039"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "build/lambda")
    args = parser.parse_args()
    build = args.output.resolve()
    build.mkdir(parents=True, exist_ok=True)
    package = build / "pkg"
    if package.exists():
        shutil.rmtree(package)
    package.mkdir()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=HERE, text=True).strip())
    version = "0.1.1-lambda-" + revision[:12] + ("-dirty" if dirty else "")
    docker = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
              "--mount", f"type=bind,source={HERE},target=/src,readonly",
              "--mount", f"type=bind,source={build},target=/out",
              "--workdir", "/src", "--env", "GOCACHE=/out/go-cache",
              "--env", "GOMODCACHE=/out/go-mod", "--env", "CGO_ENABLED=0",
              "--env", "GOTOOLCHAIN=local"]
    subprocess.run(docker + [GO_IMAGE, "go", "test", "-mod=readonly", "./..."], check=True)
    subprocess.run(docker + ["--env", "GOOS=linux", "--env", "GOARCH=arm64", GO_IMAGE,
                            "go", "build", "-mod=readonly", "-trimpath", "-buildvcs=false",
                            "-ldflags", f"-s -w -X main.version={version}",
                            "-o", "/out/pkg/idealista-mcp", "."], check=True)
    binary = package / "idealista-mcp"
    binary.chmod(0o755)
    data = binary.read_bytes()
    if data[:4] != b"\x7fELF" or int.from_bytes(data[18:20], "little") != 183:
        raise SystemExit("Expected a Linux ARM64 ELF binary")
    for name in ["lambda_handler.py", "README.md"]:
        shutil.copy2(HERE / name, package / name)
    provenance = {"revision": revision, "dirty": dirty, "version": version, "go_image": GO_IMAGE,
                  "binary_sha256": hashlib.sha256(data).hexdigest()}
    (package / "build-info.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"tested and packaged {version} (ARM64)")


if __name__ == "__main__":
    main()
