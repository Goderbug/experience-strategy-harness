#!/usr/bin/env python3
"""Persistent host-operated design roles; never invokes a model or acknowledges runtime work."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import uuid

import harness
import runtime
import role_policy as policy

DB = "engine.sqlite3"
VERSION = 1
MAX_REFS = 16
MAX_BYTES = 32 * 1024 * 1024
LIST_LIMIT = 12
# Local formats supported as a primary preview, editable design, source or patch.
# Notes and data can accompany them, but cannot alone count as a design change.
CANDIDATE_FORMATS = frozenset((
    ".html", ".htm", ".svg", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif",
    ".mp4", ".mov", ".webm", ".fig", ".sketch", ".pen", ".xd", ".psd", ".ai", ".blend",
    ".css", ".scss", ".sass", ".less", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue", ".svelte",
    ".astro", ".qml", ".swift", ".kt", ".dart", ".xib", ".storyboard", ".py", ".patch", ".diff",
))
require = harness.require


def paths(root):
    root, directory, state, runtime_db = runtime.locations(root)
    path = directory / DB
    for suffix in ("", "-journal", "-wal", "-shm"):
        part = directory / (DB + suffix)
        require(not part.is_symlink() and (not part.exists() or part.is_file()),
                "Unsafe engine database or journal.", "unsafe_path")
    return root, state, runtime_db, path


def db_read(path):
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2, isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def load_project(root, state_path, runtime_path):
    require(runtime_path.is_file(), "Initialize the strategy project and run runtime.py setup first.", "not_configured")
    with closing(db_read(runtime_path)) as db:
        config = runtime.configuration(db)
    state = harness.load(state_path)
    require(state["project"]["root"] == str(root),
            "This strategy state belongs to another project root. Do not silently rebind it.", "wrong_root")
    return state, config


def schemas(db):
    # Do not use executescript: that would implicitly commit an active transaction.
    db.execute("CREATE TABLE IF NOT EXISTS engine_meta(schema_version INTEGER, root TEXT, project_id TEXT)")
    db.execute("""CREATE TABLE IF NOT EXISTS cases(
        id TEXT PRIMARY KEY, binding TEXT UNIQUE NOT NULL, initial TEXT NOT NULL,
        snapshot TEXT NOT NULL, concern_context TEXT NOT NULL, revision INTEGER NOT NULL,
        phase TEXT NOT NULL, next_role TEXT, superseded_by TEXT, updated TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS steps(case_id TEXT NOT NULL, rev INTEGER NOT NULL,
        record TEXT NOT NULL, PRIMARY KEY(case_id, rev))""")
    db.execute("""CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, digest TEXT NOT NULL,
        receipt TEXT NOT NULL)""")


def identity(db, root, project_id=None):
    m = db.execute("SELECT schema_version,root,project_id FROM engine_meta").fetchone()
    require(m is not None and m["schema_version"] == VERSION, "Unsupported design engine database.", "invalid_engine")
    require(m["root"] == str(root) and (project_id is None or project_id == m["project_id"]),
            "This engine is bound to a different project root/ID.", "wrong_root")
    return m["project_id"]


def stage_fields(initial, binding):
    task_stage = initial.get("task_stage")
    if task_stage == "create":
        return {"task_stage": task_stage, "candidate_dir": "candidates/" + binding,
                "user_evidence": "disabled", "user_outcome": "unverified"}
    if task_stage:
        return {"task_stage": task_stage}
    return {}


def summary_if_enabled(root):
    """Bounded read-only host hint. Never hash files or replay state during host discovery."""
    root, _, runtime_path, path = paths(root)
    result = {"ok": True, "enabled": False, "root": str(root), "total_cases": 0, "cases": []}
    if not path.exists():
        return result
    require(runtime_path.exists(), "Engine exists but runtime setup is missing.", "not_configured")
    with closing(db_read(path)) as db:
        db.execute("BEGIN")
        project_id = identity(db, root)
        count = db.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        rows = db.execute("""SELECT * FROM cases ORDER BY CASE phase WHEN 'active' THEN 0
            WHEN 'waiting_evidence' THEN 1 WHEN 'needs_owner' THEN 2 ELSE 3 END, updated DESC, id LIMIT ?""",
                          (LIST_LIMIT,))
        entries = []
        for row in rows:
            data = json.loads(row["initial"])
            item = {"case_id": row["id"], "revision": row["revision"], "phase": row["phase"],
                            "next_role": row["next_role"], "binding": row["binding"], "mode": data["mode"],
                            "snapshot": row["snapshot"], "claim": data["claim"][:220]}
            item.update(stage_fields(data, row["binding"]))
            if row["phase"] in ("decided", "waiting_evidence", "needs_owner", "superseded"):
                last = db.execute("SELECT record FROM steps WHERE case_id=? ORDER BY rev DESC LIMIT 1",
                                  (row["id"],)).fetchone()
                record = json.loads(last[0]) if last else {}
                if record.get("role") == "judge":
                    item.update(outcome=record["output"]["outcome"],
                                next_trigger=record["output"]["next_trigger"][:250])
            entries.append(item)
        result.update(enabled=True, project_id=project_id, total_cases=count, cases=entries,
                      list_limit=LIST_LIMIT, truncated=count > LIST_LIMIT)
    return result


def case_of(db, cid, root, project_id):
    row = db.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
    require(row is not None, "No such case in this project: " + cid, "unknown_case")
    case = json.loads(row["initial"])
    case.update(root=str(root), project_id=project_id, binding=row["binding"], snapshot=row["snapshot"],
                concern_context=json.loads(row["concern_context"]), revision=row["revision"],
                superseded_by=row["superseded_by"],
                history=[json.loads(s["record"]) for s in db.execute(
                    "SELECT record FROM steps WHERE case_id=? ORDER BY rev", (cid,))])
    case.update(stage_fields(case, row["binding"]))
    if case.get("supersedes"):
        previous = db.execute("SELECT id,snapshot,initial FROM cases WHERE id=?", (case["supersedes"],)).fetchone()
        handoff = {"historical_only": True, "case_id": previous["id"], "snapshot": previous["snapshot"],
                   "mode": json.loads(previous["initial"])["mode"], "proposal": None, "last_judgment": None}
        previous_stage = json.loads(previous["initial"]).get("task_stage")
        if previous_stage == "create":
            handoff.update(task_stage=previous_stage, user_outcome="unverified", candidate_files=[], last_measurement=None)
        for step in db.execute("SELECT record FROM steps WHERE case_id=? ORDER BY rev DESC", (previous["id"],)):
            record = json.loads(step[0])
            out = record["output"]
            if record["role"] == "strategist" and handoff["proposal"] is None:
                handoff["proposal"] = {k: out[k][:600] for k in ("proposal", "assumption", "reopen_if")}
            if record["role"] == "judge" and handoff["last_judgment"] is None:
                handoff["last_judgment"] = {k: out[k][:600] for k in ("outcome", "rationale", "critic_response", "next_trigger")}
            if record["role"] == "execution" and not handoff.get("candidate_files"):
                handoff["candidate_files"] = record["candidate_files"]
            if record["role"] == "measurement" and not handoff.get("last_measurement"):
                handoff["last_measurement"] = {k: out[k] for k in ("outcome", "limitations")}
            if (handoff["proposal"] and handoff["last_judgment"]
                    or handoff.get("candidate_files") and handoff.get("last_measurement")):
                break
        case["predecessor_handoff"] = handoff
    return case


def stage(case):
    if case.get("superseded_by"):
        return "superseded", None
    return policy.phase(case), policy.next_role(case)


def detail(case, current, current_concern, **extra):
    phase, role = stage(case)
    brief = policy.role_brief(case) if phase != "superseded" else None
    if brief is not None:
        brief["basis"] = {k: case[k] for k in ("project_id", "root", "snapshot", "goal", "claim", "claim_type", "mode", "concern_context")}
        brief["basis"].update(stage_fields(case, case["binding"]))
        if case.get("predecessor_handoff"):
            brief["basis"]["predecessor_handoff"] = case["predecessor_handoff"]
    return dict(case, ok=True, enabled=True, phase=phase, next_role=role,
                current_snapshot=current, stale_snapshot=case["snapshot"] != current,
                stale_concern=case["concern_context"] is not None and
                (current_concern or {}).get("digest") != case["concern_context"]["digest"], brief=brief,
                **extra)


def text_field(v, label, limit=4000):
    harness.string(v, label)
    require(len(v) <= limit and "\0" not in v, label + " is too long or contains NUL.")


def validate_open(value):
    harness.fields(value, ("case_id", "goal", "claim", "claim_type", "mode"),
                   ("task_stage", "route", "signals", "concern_id", "supersedes"), label="open")
    for key in ("case_id", "concern_id", "supersedes"):
        if key in value:
            text_field(value[key], key, 160)
    for key in ("goal", "claim"):
        text_field(value[key], key)
    harness.enum(value["claim_type"], {"artifact", "behavior"}, "claim_type")
    if "task_stage" in value:
        harness.enum(value["task_stage"], {"create", "artifact_check", "user_validation"}, "task_stage")
    try:
        value["route"] = policy.choose_route(value["claim_type"], value.get("signals"), value.get("route"),
                                             value.get("task_stage"))
    except ValueError as e:
        raise harness.HarnessError("invalid_route", str(e)) from e
    value["signals"] = sorted(value.get("signals") or [])
    harness.enum(value["mode"], {"live", "fixture"}, "mode")
    require(value["route"] != "direct" or value["claim_type"] == "artifact",
            "The direct route is for artifact checks only; behavioral judgments require a tradeoff review.")
    require(value.get("supersedes") != value["case_id"], "A case cannot supersede itself.")


def bound_concern(state, cid):
    if cid is None:
        return None
    item = state["concerns"].get(cid)
    require(item is not None, "Unknown concern in this root: " + cid + ". Check the project root or explicitly hand off the concern.", "unknown_concern")
    # Freeze the authored basis. Do not silently import another project's records.
    keys = ("id", "statement", "strategy", "tradeoff", "status", "next_trigger")
    data = {k: item[k][:1500] for k in keys}
    data["alternatives"] = [s[:600] for s in item["alternatives"][:6]]
    data["validation"] = {k: item["validation"][k][:1000] for k in ("status", "version", "note")}
    data["goals"] = [{k: state["goals"][gid][k][:800] for k in ("id", "statement", "journey")}
                     for gid in item["goal_ids"][:6]]
    data["strategy_revision"] = state["revision"]
    data["digest"] = harness.digest([item, [state["goals"][gid] for gid in item["goal_ids"]]])
    return data


def open_case(args):
    value = runtime.read_input(args)
    validate_open(value)
    root, state_path, runtime_path, path = paths(args.root)
    state, config = load_project(root, state_path, runtime_path)
    project_id = state["project"]["id"]
    concern = bound_concern(state, value.get("concern_id"))
    if not path.exists():
        require("supersedes" not in value, "No previous case in this project.", "unknown_case")
        # Publish the fully initialized database with its first case. A failed
        # setup never leaves a marker that the host mistakes for an active engine.
        fd, name = tempfile.mkstemp(prefix=".engine-init-", dir=str(path.parent))
        os.close(fd)
        temporary = Path(name)
        try:
            output = add_case(temporary, root, project_id, config, value, concern, creating=True)
            try:
                os.link(str(temporary), str(path))  # atomic, never overwrites a concurrent creator
                return output
            except FileExistsError:
                pass
        finally:
            temporary.unlink()
    paths(root)
    return add_case(path, root, project_id, config, value, concern)


def add_case(path, root, project_id, config, value, concern, creating=False):
    with closing(runtime.connect(path)) as db, runtime.transaction(db):
        if creating:
            schemas(db)
            db.execute("INSERT INTO engine_meta VALUES(?,?,?)", (VERSION, str(root), project_id))
        identity(db, root, project_id)
        snap = runtime.snapshot(root, config)
        old = db.execute("SELECT initial FROM cases WHERE id=?", (value["case_id"],)).fetchone()
        if old is not None:
            require(old["initial"] == harness.canonical(value), "case_id already binds different inputs.", "case_conflict")
            return detail(case_of(db, value["case_id"], root, project_id), snap, concern, duplicate=True)
        require(snap != "files:" + harness.digest([]),
                "No files match the configured watch patterns; a design case needs a nonempty version basis.", "empty_watch")
        if "supersedes" in value:
            previous = case_of(db, value["supersedes"], root, project_id)
            require(not previous["superseded_by"], "Previous case already has a successor.", "case_conflict")
            require(previous["mode"] == value["mode"], "Cannot supersede across fixture/live modes.", "mode_conflict")
            db.execute("UPDATE cases SET superseded_by=?,phase='superseded',next_role=NULL,revision=revision+1,updated=? WHERE id=?",
                       (value["case_id"], harness.now(), previous["case_id"]))
        start = dict(value, history=[])
        binding = uuid.uuid4().hex
        if value.get("task_stage") == "create":
            candidate_dir = root / "candidates" / binding
            require(not candidate_dir.parent.is_symlink()
                    and (not candidate_dir.parent.exists() or candidate_dir.parent.is_dir())
                    and not candidate_dir.is_symlink() and not candidate_dir.exists(), "Candidate location must be new and local.", "unsafe_candidate")
        db.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,NULL,?)",
                   (value["case_id"], binding, harness.canonical(value), snap, harness.canonical(concern),
                    0, policy.phase(start), policy.next_role(start), harness.now()))
        return detail(case_of(db, value["case_id"], root, project_id), snap, concern, duplicate=False)


def proof(root, relative, remaining):
    """Open each path component relative to the previous FD, never follow links."""
    require(isinstance(relative, str) and 0 < len(relative) <= 500 and "\\" not in relative
            and ":" not in relative and not any(ord(c) < 32 for c in relative), "Invalid evidence path.", "unsafe_evidence")
    parts = relative.split("/")
    require(all(p not in ("", ".", "..") and not runtime.protected(p) and
                p.lower() not in (".codex", ".dsh", ".agents", ".config") for p in parts),
            "Evidence must be a safe file relative to this project.", "unsafe_evidence")
    require(hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd,
            "Evidence checks require POSIX no-follow openat semantics.", "unsupported_platform")
    df = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(str(root), df)
    try:
        for p in parts[:-1]:
            child = os.open(p, df, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_size <= remaining,
                    "Evidence must be a regular file within the 32 MiB aggregate limit.", "unsafe_evidence")
            h = hashlib.sha256()
            size = 0
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                require(size <= remaining, "Evidence byte limit exceeded.", "unsafe_evidence")
                h.update(chunk)
            after = os.fstat(stream.fileno())
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (size, after.st_mtime_ns, after.st_ctime_ns), "Evidence changed during read.", "stale_evidence")
            return {"path": relative, "sha256": h.hexdigest(), "bytes": size}
    except OSError as exc:
        raise harness.HarnessError("unsafe_evidence", "Cannot open this evidence within the project: " + relative) from exc
    finally:
        os.close(parent)


def fingerprints(root, refs):
    harness.strings(refs, "evidence_refs", unique=True)
    require(len(refs) <= MAX_REFS, "At most 16 file references per submission.")
    results = []
    remaining = MAX_BYTES
    for ref in refs:
        entry = proof(root, ref, remaining)
        results.append(entry)
        remaining -= entry["bytes"]
    return results


def check_reused_paths(case, files):
    previous = {item["path"]: item for step in case["history"]
                for group in ("candidate_files", "evidence_files") for item in step.get(group, ())}
    for item in files:
        require(item["path"] not in previous or previous[item["path"]] == item,
                "Previously submitted paths must keep their bytes. Restore the old version and use a new path.",
                "changed_delivery")


def design_hashes(files):
    return {item["sha256"] for item in files if Path(item["path"]).suffix.lower() in CANDIDATE_FORMATS}


def record_candidate(case, root, output):
    refs = output["candidate_refs"]
    prefix = case["candidate_dir"] + "/"
    require(all(ref.startswith(prefix) for ref in refs),
            "Put the new candidate files under this case's candidate_dir.", "unsafe_candidate")
    # Supplemental notes can travel with a candidate. Notes alone do not deliver a design.
    require(Path(refs[0]).suffix.lower() in CANDIDATE_FORMATS,
            "The candidate entry must be a local preview, design, source or patch in a supported format: "
            + ", ".join(sorted(CANDIDATE_FORMATS)), "invalid_candidate")
    files = fingerprints(root, refs)
    require(all(f["bytes"] > 0 for f in files), "Candidate files cannot be empty.", "invalid_candidate")
    old = [h for h in case["history"] if h["role"] == "execution"]
    if old:
        prior_paths = {f["path"] for h in old for f in h["candidate_files"]}
        require(refs[0] not in prior_paths, "Save a new candidate entry point for this revision.", "invalid_candidate")
        check_reused_paths(case, files)
        last = old[-1]["candidate_files"]
        require(fingerprints(root, [f["path"] for f in last]) == last,
                "Restore the previous candidate and publish the revision under new paths.", "changed_delivery")
        checks = case["history"][-1]["evidence_files"]
        require(fingerprints(root, [f["path"] for f in checks]) == checks,
                "Restore the previous check record and use a new path for changed observations.", "changed_delivery")
        require(design_hashes(files) != design_hashes(last),
                "Rework requires a changed design; notes alone cannot complete it.", "invalid_candidate")
    return files


def record_measurement(case, root, output):
    last = case["history"][-1]
    require(last["role"] == "execution", "No submitted candidate to check.", "invalid_transition")
    refs = last["output"]["candidate_refs"]
    require(not set(refs).intersection(output["evidence_refs"]),
            "Provide a record of the checks separate from the candidate itself.", "invalid_measurement")
    evidence = fingerprints(root, output["evidence_refs"])
    check_reused_paths(case, evidence)
    require(all(f["bytes"] > 0 for f in evidence), "Check records cannot be empty.", "invalid_measurement")
    require(fingerprints(root, refs) == last["candidate_files"],
            "Candidate changed after execution. Restore it or supersede this case.", "stale_candidate")
    return evidence


def creative_integrity(case, root):
    """Recheck the latest deliveries on explicit case reads; host summary stays cheap."""
    status = {"candidate": "not_submitted", "check_record": "not_submitted"}
    for step in reversed(case["history"]):
        if step["role"] == "measurement":
            key, files = "check_record", step["evidence_files"]
            if status[key] != "not_submitted":
                continue
        elif step["role"] == "execution":
            key, files = "candidate", step["candidate_files"]
        else:
            continue
        try:
            current = fingerprints(root, [f["path"] for f in files])
            status[key] = "matches" if current == files else "changed"
        except (harness.HarnessError, OSError):
            status[key] = "unreadable"
        if key == "candidate":
            break
    return status


def get_context(args):
    if not args.case_id:
        return summary_if_enabled(args.root)
    root, state_path, runtime_path, path = paths(args.root)
    require(path.exists(), "No role engine cases at this root.", "not_enabled")
    state, config = load_project(root, state_path, runtime_path)
    with closing(db_read(path)) as db:
        db.execute("BEGIN")
        pid = identity(db, root, state["project"]["id"])
        case = case_of(db, args.case_id, root, pid)
        result = detail(case, runtime.snapshot(root, config), bound_concern(state, case.get("concern_id")))
        if case.get("task_stage") == "create":
            result["artifact_integrity"] = creative_integrity(case, root)
        return result


def advance(args):
    action = args.command
    value = runtime.read_input(args)
    core = ("case_id", "binding", "expected_revision", "request_id")
    harness.fields(value, core + (("role", "output") if action == "submit" else ("reason",)), label=action)
    for key in ("case_id", "binding", "request_id"):
        text_field(value[key], key, 160)
    harness.integer(value["expected_revision"], "expected_revision")
    if action == "resume":
        text_field(value["reason"], "reason")
    require(len(harness.canonical(value).encode("utf-8")) <= 128*1024, "Role request exceeds 128 KiB.")
    root, state_path, runtime_path, path = paths(args.root)
    require(path.exists(), "Open a role case at this project first.", "not_enabled")
    state, config = load_project(root, state_path, runtime_path)
    rid = value["request_id"]
    digest = harness.digest([action, value])
    with closing(runtime.connect(path)) as db, runtime.transaction(db):
        pid = identity(db, root, state["project"]["id"])
        case = case_of(db, value["case_id"], root, pid)
        require(value["binding"] == case["binding"], "Case binding does not match this project/case instance.", "wrong_binding")
        snap = runtime.snapshot(root, config)
        current_concern = bound_concern(state, case.get("concern_id"))
        receipt = db.execute("SELECT digest,receipt FROM receipts WHERE id=?", (rid,)).fetchone()
        if receipt is not None:
            require(receipt["digest"] == digest, "request_id already binds a different request.", "request_conflict")
            return detail(case, snap, current_concern, receipt=json.loads(receipt["receipt"]), duplicate=True)
        require(not case["superseded_by"], "This case has been superseded.", "superseded_case")
        require(case["revision"] == value["expected_revision"], "Stale role revision; read current context.", "stale_revision")
        require(case["snapshot"] == snap, "Watched files changed. Inspect the change, then open a new case with supersedes.", "stale_snapshot")
        if current_concern is not None:
            require(current_concern["digest"] == case["concern_context"]["digest"],
                    "The bound concern or its goals changed; inspect current strategy and open a successor.", "stale_concern")
        now = harness.now()
        if action == "resume":
            require(policy.phase(case) == "waiting_evidence", "Only a waiting_evidence case can resume for a new observation.", "invalid_transition")
            record = {"role": "resume", "output": {"reason": value["reason"]}}
        else:
            role = value["role"]
            require(role == policy.next_role(case) and role is not None, "Wrong role for this phase.", "wrong_role")
            try:
                policy.validate_output(case, role, value["output"])
            except ValueError as e:
                raise harness.HarnessError("invalid_role_output", str(e)) from e
            record = {"role": role, "output": value["output"]}
            if role == "execution":
                record["candidate_files"] = record_candidate(case, root, value["output"])
            if role == "measurement":
                record["evidence_files"] = record_measurement(case, root, value["output"])
                record["candidate_revision"] = case["revision"]
            if role in {"verifier", "user_evidence"}:
                record["evidence_files"] = fingerprints(root, value["output"]["evidence_refs"])
            if role == "judge":
                latest = case["history"][-1]
                current = fingerprints(root, latest["output"]["evidence_refs"])
                require(current == latest["evidence_files"],
                        "Evidence bytes changed after verification; inspect and open a replacement case.", "stale_evidence")
        require(runtime.snapshot(root, config) == snap, "Watched files changed during this step.", "stale_snapshot")
        rev = case["revision"] + 1
        case["revision"] = rev
        record.update(revision=rev, request_id=rid, recorded_at=now)
        case["history"].append(record)
        phase, role = stage(case)
        receipt = {"request_id": rid, "action": action, "case_id": case["case_id"], "binding": case["binding"],
                   "revision": rev, "phase": phase, "next_role": role, "snapshot": snap}
        db.execute("INSERT INTO steps VALUES(?,?,?)", (case["case_id"], rev, harness.canonical(record)))
        db.execute("INSERT INTO receipts VALUES(?,?,?)", (rid, digest, harness.canonical(receipt)))
        db.execute("UPDATE cases SET revision=?,phase=?,next_role=?,updated=? WHERE id=?", (rev, phase, role, now, case["case_id"]))
        return detail(case, snap, current_concern, receipt=receipt, duplicate=False)


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest="command", required=True)
    for action, func in (("open", open_case), ("context", get_context), ("submit", advance), ("resume", advance)):
        cmd = subs.add_parser(action)
        cmd.add_argument("--root", required=True)
        if action == "context":
            cmd.add_argument("--case-id")
        else:
            cmd.add_argument("--input", default="-", help="JSON path, or - for stdin")
        cmd.set_defaults(run=func)
    return ap


def main():
    args = parser().parse_args()
    try:
        print(harness.canonical(args.run(args)))
        return 0
    except (harness.HarnessError, OSError, ValueError, sqlite3.Error) as exc:
        print(harness.canonical({"ok": False, "error": getattr(exc, "code", "engine_error"), "message": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
