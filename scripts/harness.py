#!/usr/bin/env python3
"""Portable, dependency-free checkpoint storage for an experience strategy host agent.

This helper persists decisions. It does not observe a product, run a model,
schedule work, or establish that a recorded validation result is true.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone


HARNESS_VERSION = "0.1.0"
SCHEMA_VERSION = 1
MODES = {"analysis-only", "prototype", "implementation"}
NODES = {"intake", "before-change", "after-change", "feedback", "resume", "handoff"}
KINDS = {"document", "observation", "user-report", "runtime-test", "simulation"}
STATUSES = {"open", "in-progress", "awaiting-validation", "resolved", "deferred", "dismissed"}
COLLECTIONS = ("goals", "evidence", "concerns", "decisions")
CAPABILITIES = {
    "host_checkpoints": True,
    "background_monitoring": False,
    "observer_configured": False,
    "model_calls": False,
}


class HarnessError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, message, code="invalid_input"):
    if not condition:
        raise HarnessError(code, message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fields(value, required, optional=(), label="object"):
    require(isinstance(value, dict), label + " must be an object.")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    require(not missing, label + " is missing: " + ", ".join(sorted(missing)))
    require(not extra, label + " has unknown fields: " + ", ".join(sorted(extra)))


def string(value, label, nonempty=True):
    require(isinstance(value, str), label + " must be a string.")
    require(not nonempty or bool(value.strip()), label + " must not be blank.")


def strings(value, label, unique=False):
    require(isinstance(value, list), label + " must be an array.")
    for item in value:
        string(item, label + " item")
    require(not unique or len(value) == len(set(value)), label + " must contain unique IDs.")


def enum(value, values, label):
    require(isinstance(value, str) and value in values, label + " must be one of: " + ", ".join(sorted(values)))


def integer(value, label):
    require(type(value) is int and value >= 0, label + " must be a nonnegative integer.")


def read_json(stream):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON field: " + key)
            result[key] = value
        return result

    def constant(value):
        raise HarnessError("invalid_input", "Non-finite JSON value is not allowed: " + value)

    try:
        return json.load(stream, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        raise HarnessError("invalid_json", "Cannot parse JSON: " + str(exc)) from exc


def validate_record(collection, record):
    common = ("id",)
    if collection == "goals":
        fields(record, common + ("statement", "journey", "active"), label="goal")
        for key in ("id", "statement", "journey"):
            string(record[key], "goal." + key)
        require(type(record["active"]) is bool, "goal.active must be a boolean.")
    elif collection == "evidence":
        fields(record, common + ("kind", "source", "summary", "version"), label="evidence")
        for key in ("id", "source", "summary", "version"):
            string(record[key], "evidence." + key)
        enum(record["kind"], KINDS, "evidence.kind")
    elif collection == "decisions":
        fields(record, common + ("concern_ids", "choice", "reason", "origin", "source", "version"), label="decision")
        for key in ("id", "choice", "reason", "source", "version"):
            string(record[key], "decision." + key)
        strings(record["concern_ids"], "decision.concern_ids", unique=True)
        enum(record["origin"], {"agent", "user"}, "decision.origin")
    else:
        fields(record, common + ("kind", "goal_ids", "statement", "basis", "status", "evidence_ids",
                                 "strategy", "alternatives", "tradeoff", "next_trigger", "validation"),
               ("resolution_reason",), "concern")
        for key in ("id", "statement", "strategy", "tradeoff", "next_trigger"):
            string(record[key], "concern." + key)
        for key in ("goal_ids", "evidence_ids"):
            strings(record[key], "concern." + key, unique=True)
        require(record["goal_ids"], "Every concern must link at least one goal.")
        strings(record["alternatives"], "concern.alternatives")
        enum(record["kind"], {"issue", "opportunity"}, "concern.kind")
        enum(record["basis"], {"observed", "reported", "hypothesis"}, "concern.basis")
        enum(record["status"], STATUSES, "concern.status")
        validation = record["validation"]
        fields(validation, ("status", "evidence_ids", "version", "note"), label="concern.validation")
        enum(validation["status"], {"unverified", "pass", "fail"}, "concern.validation.status")
        strings(validation["evidence_ids"], "concern.validation.evidence_ids", unique=True)
        string(validation["version"], "concern.validation.version")
        string(validation["note"], "concern.validation.note")
        if "resolution_reason" in record:
            string(record["resolution_reason"], "concern.resolution_reason")
        if record["status"] in {"resolved", "deferred", "dismissed"}:
            require(record.get("resolution_reason"), "Resolved/deferred/dismissed concerns require resolution_reason.")


def validate_links(state):
    for name in COLLECTIONS:
        require(isinstance(state[name], dict), "State collection " + name + " must be an object.", "invalid_state")
        for key, record in state[name].items():
            validate_record(name, record)
            require(key == record["id"], "Stored record key does not match its ID.", "invalid_state")
    for concern in state["concerns"].values():
        cid = concern["id"]
        for gid in concern["goal_ids"]:
            require(gid in state["goals"], cid + " references unknown goal: " + gid)
        for eid in concern["evidence_ids"] + concern["validation"]["evidence_ids"]:
            require(eid in state["evidence"], cid + " references unknown evidence: " + eid)
        require(set(concern["validation"]["evidence_ids"]).issubset(concern["evidence_ids"]),
                cid + ": validation evidence must also appear in concern.evidence_ids.")
        if concern["status"] == "resolved":
            validation = concern["validation"]
            require(validation["status"] == "pass", cid + ": resolved requires validation.status=pass.")
            eligible = [state["evidence"][eid] for eid in validation["evidence_ids"]
                        if state["evidence"][eid]["kind"] in {"observation", "runtime-test", "user-report"}
                        and state["evidence"][eid]["version"] == validation["version"]]
            require(eligible, cid + ": resolved requires observation, runtime-test, or user-report evidence matching the validation version; documents and simulations alone cannot close it.")
    for decision in state["decisions"].values():
        for cid in decision["concern_ids"]:
            require(cid in state["concerns"], decision["id"] + " references unknown concern: " + cid)


def validate_state(state):
    fields(state, ("schema_version", "harness_version", "online", "capabilities", "revision", "created_at",
                   "updated_at", "initialization", "project", "goals", "evidence", "concerns", "decisions",
                   "checkpoints", "requests"), label="state")
    require(type(state["schema_version"]) is int and state["schema_version"] == SCHEMA_VERSION,
            "Unsupported state schema; use the matching harness version.", "invalid_state")
    require(state["harness_version"] == HARNESS_VERSION,
            "Unsupported harness version; use the matching helper before changing this state.", "invalid_state")
    require(state["online"] is False and state["capabilities"] == CAPABILITIES,
            "This helper cannot claim background monitoring or model execution.", "invalid_state")
    project = state["project"]
    fields(project, ("id", "root", "goal", "scope", "mode", "version"), label="project")
    for key in ("id", "root", "goal", "scope", "version"):
        string(project[key], "project." + key)
    enum(project["mode"], MODES, "project.mode")
    fields(state["initialization"], ("id", "root", "goal", "scope", "mode", "version"), label="initialization")
    for key in ("id", "root", "goal", "scope", "version"):
        string(state["initialization"][key], "initialization." + key)
    enum(state["initialization"]["mode"], MODES, "initialization.mode")
    string(state["created_at"], "created_at")
    string(state["updated_at"], "updated_at")
    integer(state["revision"], "state.revision")
    require(isinstance(state["checkpoints"], list), "state.checkpoints must be an array.", "invalid_state")
    require(isinstance(state["requests"], dict), "state.requests must be an object.", "invalid_state")
    require(state["revision"] == len(state["checkpoints"]) == len(state["requests"]),
            "Revision/checkpoint/request counts disagree; restore a known-good export rather than editing history.", "invalid_state")
    replay = {"project": copy.deepcopy(state["initialization"]),
              "goals": {"goal-primary": {"id": "goal-primary", "statement": state["initialization"]["goal"],
                                          "journey": state["initialization"]["scope"], "active": True}},
              "evidence": {}, "concerns": {}, "decisions": {}}
    for index, checkpoint in enumerate(state["checkpoints"], 1):
        require(isinstance(checkpoint, dict) and checkpoint.get("revision") == index,
                "Checkpoint history is not sequential.", "invalid_state")
        fields(checkpoint, ("revision", "recorded_at", "input", "before", "receipt"), label="checkpoint")
        envelope = checkpoint["input"]
        validate_envelope(envelope)
        require(envelope["expected_revision"] == index - 1,
                "Checkpoint input revision is not sequential.", "invalid_state")
        require(checkpoint["before"] == {name: replay[name] for name in ("project", "goals", "concerns")},
                "Checkpoint before-snapshot does not match history.", "invalid_state")
        request_id = envelope["request_id"]
        request = state["requests"].get(request_id)
        require(isinstance(request, dict) and isinstance(request.get("receipt"), dict)
                and request.get("digest") == digest(envelope)
                and request.get("receipt") == checkpoint.get("receipt")
                and request["receipt"].get("revision") == index,
                "Checkpoint request record is inconsistent.", "invalid_state")
        replay["project"].update(envelope.get("project_update", {}))
        replay["project"]["version"] = envelope["project_version"]
        for name in COLLECTIONS:
            for record in envelope.get(name, []):
                replay[name][record["id"]] = copy.deepcopy(record)
    require(all(state[name] == replay[name] for name in ("project",) + COLLECTIONS),
            "Current state does not match checkpoint history; restore a known-good export rather than editing state.json.", "invalid_state")
    validate_links(state)


def locations(root):
    root = Path(root).expanduser()
    require(root.is_dir(), "--root must be an existing project directory.", "invalid_root")
    root = root.resolve()
    directory = root / ".experience-strategy"
    require(not directory.is_symlink(), "Refusing symlink .experience-strategy directory; choose a real project-local state directory.", "unsafe_path")
    require(not directory.exists() or directory.is_dir(), ".experience-strategy exists but is not a directory.", "unsafe_path")
    for name in ("state.json", "write.lock"):
        path = directory / name
        require(not path.is_symlink(), "Refusing symlink " + str(path) + "; remove the link explicitly before retrying.", "unsafe_path")
        require(not path.exists() or path.is_file(), str(path) + " must be a regular file.", "unsafe_path")
    return root, directory, directory / "state.json"


@contextmanager
def locked(directory):
    lock = directory / "write.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(lock), flags, 0o600)
    except FileExistsError as exc:
        raise HarnessError("locked", "State is locked at " + str(lock)
                           + ". Wait for the current writer. If it has stopped, inspect the lock, confirm no writer is running, then remove only write.lock and retry; this helper never removes an existing lock.") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical({"pid": os.getpid(), "created_at": now()}))
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        lock.unlink()


def atomic_write(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(path.parent),
                                         prefix=".state-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        require(not path.is_symlink(), "State path became a symlink; refusing to replace it.", "unsafe_path")
        os.replace(str(temporary), str(path))
        temporary = None
        if hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load(path):
    require(path.exists(), "No state found. Run init for this project first.", "not_initialized")
    with path.open(encoding="utf-8") as stream:
        state = read_json(stream)
    validate_state(state)
    return state


def initialize(args):
    root, directory, path = locations(args.root)
    initialization = {"id": args.project_id, "root": str(root), "goal": args.goal,
                      "scope": args.scope, "mode": args.mode, "version": args.version}
    for key, value in initialization.items():
        string(value, "init." + key)
    directory.mkdir(exist_ok=True)
    with locked(directory):
        if path.exists():
            state = load(path)
            require(state["initialization"] == initialization,
                    "Project state already exists with different initialization. Use context to inspect it, then commit project_update for an intentional focus change; init never overwrites.", "already_initialized")
            return {"ok": True, "action": "init", "created": False, "revision": state["revision"],
                    "state_path": str(path), "online": False}
        timestamp = now()
        state = {"schema_version": SCHEMA_VERSION, "harness_version": HARNESS_VERSION,
                 "online": False, "capabilities": CAPABILITIES.copy(), "revision": 0,
                 "created_at": timestamp, "updated_at": timestamp,
                 "initialization": initialization, "project": initialization.copy(),
                 "goals": {"goal-primary": {"id": "goal-primary", "statement": args.goal,
                                             "journey": args.scope, "active": True}},
                 "evidence": {}, "concerns": {}, "decisions": {}, "checkpoints": [], "requests": {}}
        validate_state(state)
        atomic_write(path, state)
    return {"ok": True, "action": "init", "created": True, "revision": 0,
            "state_path": str(path), "online": False}


def validate_envelope(envelope):
    fields(envelope, ("request_id", "expected_revision", "node", "project_version", "change", "depth",
                      "reason", "summary", "next_action", "limitations"), COLLECTIONS + ("project_update",), "commit")
    for key in ("request_id", "project_version", "change", "reason", "summary", "next_action"):
        string(envelope[key], "commit." + key)
    integer(envelope["expected_revision"], "commit.expected_revision")
    enum(envelope["node"], NODES, "commit.node")
    enum(envelope["depth"], {"none", "focused", "full"}, "commit.depth")
    strings(envelope["limitations"], "commit.limitations")
    for name in COLLECTIONS:
        records = envelope.get(name, [])
        require(isinstance(records, list), "commit." + name + " must be an array.")
        ids = []
        for record in records:
            validate_record(name, record)
            ids.append(record["id"])
        require(len(ids) == len(set(ids)), "Duplicate IDs in commit." + name)
    if "project_update" in envelope:
        update = envelope["project_update"]
        fields(update, (), ("goal", "scope", "mode"), "project_update")
        require(update, "project_update must contain at least one field.")
        for key in ("goal", "scope"):
            if key in update:
                string(update[key], "project_update." + key)
        if "mode" in update:
            enum(update["mode"], MODES, "project_update.mode")


def commit(args):
    if args.input == "-":
        envelope = read_json(sys.stdin)
    else:
        with Path(args.input).expanduser().open(encoding="utf-8") as stream:
            envelope = read_json(stream)
    validate_envelope(envelope)
    root, directory, path = locations(args.root)
    require(directory.exists(), "No state found. Run init first.", "not_initialized")
    with locked(directory):
        state = load(path)
        request_id = envelope["request_id"]
        previous_request = state["requests"].get(request_id)
        request_digest = digest(envelope)
        if previous_request:
            require(previous_request["digest"] == request_digest,
                    "request_id already exists with a different body. Use a fresh request_id for a new checkpoint.", "request_conflict")
            return previous_request["receipt"]
        require(envelope["expected_revision"] == state["revision"],
                "Stale revision: expected " + str(envelope["expected_revision"]) + ", current " + str(state["revision"])
                + ". Run context, reconcile new evidence, and submit with the current revision and a fresh request_id.", "stale_revision")
        before = {name: copy.deepcopy(state[name]) for name in ("project", "goals", "concerns")}
        state["project"].update(envelope.get("project_update", {}))
        state["project"]["version"] = envelope["project_version"]
        for name in COLLECTIONS:
            for record in envelope.get(name, []):
                old = state[name].get(record["id"])
                if name in {"evidence", "decisions"} and old is not None:
                    require(old == record, name + " record " + record["id"] + " is immutable; add a new ID and explain the correction.", "immutable_record")
                if name == "concerns":
                    if old and old["status"] == "resolved" and record["status"] != "resolved":
                        require(record.get("resolution_reason"), record["id"] + ": reopening a resolved concern requires resolution_reason.")
                    if record["status"] == "resolved":
                        require(record["validation"]["version"] == envelope["project_version"],
                                record["id"] + ": resolved validation.version must match this checkpoint's project_version.")
                state[name][record["id"]] = copy.deepcopy(record)
        timestamp = now()
        revision = state["revision"] + 1
        receipt = {"ok": True, "action": "commit", "request_id": request_id, "revision": revision,
                   "project_version": envelope["project_version"], "node": envelope["node"],
                   "online": False, "state_path": str(path)}
        checkpoint = {"revision": revision, "recorded_at": timestamp, "input": copy.deepcopy(envelope),
                      "before": before, "receipt": receipt.copy()}
        state["checkpoints"].append(checkpoint)
        state["requests"][request_id] = {"digest": request_digest, "receipt": receipt.copy()}
        state["revision"] = revision
        state["updated_at"] = timestamp
        validate_state(state)
        atomic_write(path, state)
    return receipt


def context(args):
    root, _, path = locations(args.root)
    state = load(path)
    return {"ok": True, "action": "context", "revision": state["revision"],
            "online": False, "capabilities": state["capabilities"], "state_path": str(path),
            "project_root_moved": state["project"]["root"] != str(root),
            "runtime_note": "Persistence is available. No background observer is configured; a host agent must invoke each checkpoint.",
            "project": state["project"], "goals": list(state["goals"].values()),
            "concerns": list(state["concerns"].values()), "evidence": list(state["evidence"].values()),
            "decisions": list(state["decisions"].values()),
            "latest_checkpoint": state["checkpoints"][-1]["input"] if state["checkpoints"] else None,
            "validation_note": "Recorded pass results describe the cited scope; the helper does not verify evidence or human acceptance."}


def validate(args):
    _, _, path = locations(args.root)
    state = load(path)
    return {"ok": True, "action": "validate", "revision": state["revision"], "online": False,
            "counts": {name: len(state[name]) for name in COLLECTIONS},
            "validation_scope": "JSON schema, references, lifecycle invariants, and checkpoint consistency only; product outcomes and provenance are not independently verified."}


def export(args):
    _, _, path = locations(args.root)
    state = load(path)
    output = Path(args.output).expanduser().absolute()
    require(not output.exists() and not output.is_symlink(), "Export output already exists. Choose a new directory; exports never overwrite.", "output_exists")
    require(output.parent.is_dir(), "Export parent directory must already exist.", "invalid_output")
    try:
        output.mkdir()
    except FileExistsError as exc:
        raise HarnessError("output_exists", "Export directory was created by another writer; choose a new directory.") from exc
    with (output / "state.json").open("x", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with (output / "checkpoints.jsonl").open("x", encoding="utf-8") as stream:
        for checkpoint in state["checkpoints"]:
            stream.write(canonical(checkpoint) + "\n")
    report = """# Experience strategy experiment return report

This is a scaffold, not an evaluation or proof of improvement. Fill it using the
bundled harness `templates/RETURN-REPORT.md` as the full reporting guide.

## Recorded run

- Harness version: {harness}
- Project ID: {project}
- Project version: {version}
- Revision / checkpoints: {revision}
- Execution mode: {mode}
- Background observation: not configured; host-invoked checkpoints only.
- Included: state.json and checkpoints.jsonl. Source materials were not copied.

## Environment and scope

TODO: host agent/model/version, project baseline, available tools, budget, task,
actual checkpoints performed, skipped checkpoints, and privacy redactions.

## What changed because of the harness

TODO: cite concern/decision/evidence IDs, before/after behavior, rejected or
withdrawn advice, added work, and unresolved concerns. Do not infer improvement
from report length, advice count, or implementation alone.

## Validation and limitations

TODO: distinguish document claims, agent inferences, simulations, runtime tests,
and external human evidence. State exact versions and tested journeys. If no
comparison was run, say so; do not invent a baseline or user acceptance.

## Continuity and handoff

TODO: did a fresh agent recover the goals and outstanding issues, retain
awaiting-validation items, avoid repeated advice, and reopen relevant issues?
List next triggers, next actions, failures, and specific changes to the harness.
""".format(harness=HARNESS_VERSION, project=state["project"]["id"], version=state["project"]["version"],
           revision=state["revision"], mode=state["project"]["mode"])
    with (output / "RETURN-REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report)
    return {"ok": True, "action": "export", "revision": state["revision"], "online": False,
            "output": str(output), "files": ["state.json", "checkpoints.jsonl", "RETURN-REPORT.md"],
            "source_materials_copied": False}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize or identically resume project state; never overwrite.")
    init.add_argument("--root", required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--goal", required=True)
    init.add_argument("--scope", required=True)
    init.add_argument("--version", required=True)
    init.add_argument("--mode", choices=sorted(MODES), default="analysis-only")
    init.set_defaults(run=initialize)
    for name, function in (("context", context), ("commit", commit), ("validate", validate), ("export", export)):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True)
        command.set_defaults(run=function)
        if name == "commit":
            command.add_argument("--input", required=True, help="Checkpoint JSON path, or - for stdin.")
        if name == "export":
            command.add_argument("--output", required=True, help="New directory under an existing parent.")
    return result


def main():
    try:
        args = parser().parse_args()
        print(json.dumps(args.run(args), ensure_ascii=False, allow_nan=False))
        return 0
    except HarnessError as exc:
        print(json.dumps({"ok": False, "error": exc.code, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps({"ok": False, "error": "io_error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
