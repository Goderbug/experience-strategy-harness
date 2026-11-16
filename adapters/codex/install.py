#!/usr/bin/env python3
"""Install or remove only this adapter's project-local Codex hook handlers."""

import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile


ADAPTER_ID = "experience-strategy-harness"
MARKER = "--adapter-id=" + ADAPTER_ID
REPO_ROOT = Path(__file__).resolve().parents[2]


def owned(handler):
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    try:
        return MARKER in shlex.split(handler.get("command", ""))
    except (TypeError, ValueError):
        return False


def update(existing, command, uninstall=False):
    if not isinstance(existing, dict) or not isinstance(existing.get("hooks", {}), dict):
        raise ValueError("Existing hooks.json must contain an object of hook events.")
    output = copy.deepcopy(existing)
    events = output.setdefault("hooks", {})
    for name, groups in list(events.items()):
        if not isinstance(groups, list):
            raise ValueError("Existing event %s must be an array." % name)
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("Existing event %s has an invalid matcher group." % name)
            handlers = [handler for handler in group["hooks"] if not owned(handler)]
            if handlers or not group["hooks"]:
                retained.append(dict(group, hooks=handlers))
        if retained:
            events[name] = retained
        else:
            events.pop(name)
    if not uninstall:
        template = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        for name, groups in template["hooks"].items():
            groups = copy.deepcopy(groups)
            for group in groups:
                for handler in group["hooks"]:
                    handler["command"] = command
            events.setdefault(name, []).extend(groups)
    return output


def install(root, uninstall=False):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root must be an existing directory.")
    directory = root / ".codex"
    target = directory / "hooks.json"
    if directory.is_symlink() or target.is_symlink():
        raise ValueError("Refusing a symlinked .codex directory or hooks.json file.")
    if uninstall and not target.exists():
        return {"changed": False, "path": str(target), "removed": True}
    directory.mkdir(exist_ok=True)
    lock = directory / "experience-strategy-install.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("Another installer may be running; inspect experience-strategy-install.lock before retrying.") from exc
    os.close(descriptor)
    temporary = None
    try:
        original = target.read_text(encoding="utf-8") if target.exists() else None
        existing = json.loads(original) if original is not None else {}
        command = " ".join([shlex.quote(sys.executable), shlex.quote(str(REPO_ROOT / "adapters" / "codex" / "hook.py")), MARKER])
        revised = update(existing, command, uninstall)
        changed = revised != existing
        if changed:
            fd, temporary = tempfile.mkstemp(prefix=".experience-hooks-", suffix=".json", dir=str(directory))
            mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(revised, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, target)
            temporary = None
        return {"changed": changed, "path": str(target), "removed": uninstall,
                "trust_required": not uninstall,
                "note": "Review the project and these exact hooks in Codex /hooks or Settings > Hooks. This installer does not grant trust."}
    finally:
        if temporary:
            os.unlink(temporary)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.root, args.uninstall), ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
