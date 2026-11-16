#!/usr/bin/env python3
"""Translate trusted Codex lifecycle hooks to the local experience runtime.

No API key, transcript read, prompt storage, model call, or permission change.
The host agent performs the review prompted by the runtime's additional context.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid


ADAPTER_ID = "experience-strategy-harness"
REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "turn-start",
    "PreToolUse": "before-tool",
    "PostToolUse": "tool-result",
    "Stop": "stop",
    "Interrupt": "interrupt",
    "SessionEnd": "session-end",
}
CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"}
MAX_INPUT_BYTES = 4 * 1024 * 1024


def project_root(cwd):
    """Only an explicitly configured runtime can activate this plugin."""
    if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
        raise ValueError("Codex hook cwd must be an absolute directory.")
    current = Path(cwd).resolve(strict=True)
    if not current.is_dir():
        raise ValueError("Codex hook cwd is not a directory.")
    for parent in (current,) + tuple(current.parents):
        directory = parent / ".experience-strategy"
        if directory.is_symlink():
            raise ValueError("Refusing a symlinked .experience-strategy directory.")
        marker = directory / "runtime.sqlite3"
        if marker.exists() or marker.is_symlink():
            if marker.is_symlink() or not marker.is_file():
                raise ValueError("Experience runtime database must be a regular file.")
            return parent
    return None


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError("Hook input must be a JSON object.")
    native = payload.get("hook_event_name")
    if native not in EVENTS:
        return None
    session = payload.get("session_id")
    turn = payload.get("turn_id", "")
    if not isinstance(session, str) or not session.strip():
        raise ValueError("Codex hook session_id is missing.")
    if not isinstance(turn, str):
        raise ValueError("Codex hook turn_id must be a string.")
    continuation = payload.get("stop_hook_active", False)
    if not isinstance(continuation, bool):
        raise ValueError("stop_hook_active must be a boolean.")
    # Tool IDs and turn IDs are stable across delivery retries. Lifecycle events
    # without native IDs (including repeated compaction/resume) need fresh IDs.
    tool_id = payload.get("tool_use_id")
    if native in {"PreToolUse", "PostToolUse"} and isinstance(tool_id, str) and tool_id:
        identity = [session, turn, native, tool_id]
    elif turn and native in {"UserPromptSubmit", "Stop", "Interrupt"}:
        identity = [session, turn, native, continuation]
    else:
        identity = [session, turn, native, str(uuid.uuid4())]
    event = {
        "host": "codex",
        "session_id": session,
        "turn_id": turn,
        "event_id": "codex-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
        "event": EVENTS[native],
    }
    if native in {"PreToolUse", "PostToolUse"}:
        name = payload.get("tool_name", "unknown")
        if not isinstance(name, str):
            raise ValueError("tool_name must be a string.")
        event["tool_name"] = name
    if native == "Stop":
        event["continuation"] = continuation
    return event


def call_runtime(root, event):
    timeout = 1.8 if event["event"] in {"interrupt", "session-end"} else 8
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "runtime.py"), "event", "--root", str(root)],
        input=json.dumps(event), text=True, capture_output=True, timeout=timeout,
    )
    if result.returncode:
        # Avoid reflecting arbitrary subprocess output into privileged context.
        raise RuntimeError("Runtime event command failed (exit %s). Run runtime.py context to diagnose." % result.returncode)
    output = json.loads(result.stdout)
    if not isinstance(output, dict) or output.get("ok") is not True:
        raise RuntimeError("Runtime did not return a successful event receipt.")
    return output


def dispatch(payload, runner=call_runtime):
    event = normalize(payload)
    if event is None:
        return {}
    root = project_root(payload.get("cwd"))
    if root is None:
        return {}
    result = runner(root, event)
    if result.get("enabled") is not True:
        return {}
    native = payload["hook_event_name"]
    context = result.get("context", "")
    if not isinstance(context, str):
        raise ValueError("Runtime context must be a string.")
    warning = result.get("warning")
    output = {}
    if native in CONTEXT_EVENTS and context:
        output["hookSpecificOutput"] = {
            "hookEventName": native,
            "additionalContext": context,
        }
    # The native flag is a second bound even if a runtime regression says block.
    if native == "Stop" and result.get("block_stop") is True and not event.get("continuation"):
        if context:
            output.update(decision="block", reason=context)
        else:
            warning = "Experience review is pending, but no continuation instructions were returned."
    if warning and native != "SessionEnd":
        output["systemMessage"] = str(warning)
    # Interrupt/SessionEnd are advisory only; never resume a cancelled session.
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-id", choices=[ADAPTER_ID], default=ADAPTER_ID)
    parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Hook input exceeds the 4 MiB limit.")
        payload = json.loads(raw)
        output = dispatch(payload)
    except Exception as exc:
        # Fail open, with visible uncertainty. A broken review must not lock the
        # user in an unbounded Stop continuation or override their interruption.
        output = {"systemMessage": "Experience strategy hook could not run; review status is unverified. " + str(exc)}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
