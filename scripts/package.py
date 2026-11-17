#!/usr/bin/env python3
"""Package tracked release files; never include project state or local credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

VERSION = "0.3.0-alpha.2"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New release directory; never overwritten")
    parser.add_argument("--deepseek-tarball", help="Already built npm pack artifact")
    args = parser.parse_args()
    output = Path(args.output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        parser.error("Output exists; choose a new directory.")
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    files = []
    for name in filter(None, paths):
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            parser.error("Tracked source must be a regular file: " + name)
        if any(part in {".experience-strategy", ".experience-strategy-portable", "node_modules", ".git"} for part in path.relative_to(ROOT).parts):
            parser.error("Refusing runtime or dependency data: " + name)
        if path.name.startswith(".env"):
            parser.error("Refusing environment file: " + name)
        files.append((name, path.read_bytes()))
    if not files:
        parser.error("No tracked files; commit or stage the reviewed release source first.")
    output.mkdir(parents=True)
    archive = output / ("experience-strategy-harness-v" + VERSION + ".zip")
    prefix = "experience-strategy-harness/"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as handle:
        for name, data in sorted(files):
            info = zipfile.ZipInfo(prefix + name, (2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            handle.writestr(info, data)
    for name in ("VALIDATION.md", "EXPERIENCE-HARNESS.md"):
        shutil.copyfile(ROOT / name, output / name)
    if args.deepseek_tarball:
        source = Path(args.deepseek_tarball).resolve(strict=True)
        if not source.is_file() or source.suffix != ".tgz":
            parser.error("DeepSeek artifact must be an existing .tgz")
        shutil.copyfile(source, output / source.name)
    checks = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(output.iterdir()) if path.is_file()}
    (output / "SHA256SUMS.txt").write_text("".join(value + "  " + name + "\n" for name, value in checks.items()))
    (output / "SHA256SUMS.json").write_text(json.dumps({"version": VERSION, "files": checks}, indent=2) + "\n")
    print(json.dumps({"output": str(output), "files": sorted(p.name for p in output.iterdir()), "source_files": len(files)}))


if __name__ == "__main__":
    main()
