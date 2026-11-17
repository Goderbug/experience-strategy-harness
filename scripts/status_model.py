"""Read durable project, runtime and role records without observing or acknowledging events."""
from contextlib import closing, contextmanager
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3

import engine
import harness
import runtime


# Keys are explicit: internal requests, bindings, participant identifiers and raw
# checkpoint payloads do not belong in the status surface.
LABELS = {
    "change": "设计改动", "tradeoff": "取舍", "acceptance": "验收条件",
    "intent": "意图", "options": "备选", "proposal": "提案", "assumption": "假设",
    "reopen_if": "重开条件", "objection": "异议", "consequence": "可能后果",
    "check": "检验办法", "reason": "理由", "review_steps": "查看方法",
    "outcome": "结论", "rationale": "依据", "critic_response": "异议回应",
    "next_trigger": "下次触发条件", "method": "方法", "provenance": "来源",
    "finding": "核验结果", "task": "任务", "observation": "观察", "scope": "范围",
    "limitations": "限制",
}
READ_ERRORS = (harness.HarnessError, OSError, sqlite3.Error, ValueError, TypeError, KeyError)


@lru_cache(maxsize=12)
def _strategy(path, fingerprint):
    # The atomic state writer replaces the file. Validate a changed revision once,
    # then retain only the fields required for the read model.
    state = harness.load(path)
    return {key: state[key] for key in ("project", "goals", "concerns")}


@contextmanager
def _read_db(path):
    for suffix in ("", "-wal", "-shm", "-journal"):
        item = path.with_name(path.name + suffix)
        harness.require(not item.is_symlink() and (not item.exists() or item.is_file()),
                        "Unsafe status database path.", "unsafe_path")
    # The Harness uses rollback journals. SQLite may create or change a shared
    # memory sidecar even in mode=ro for an externally switched WAL database.
    with path.open("rb") as stream:
        header = stream.read(20)
    harness.require(len(header) == 20 and header[:16] == b"SQLite format 3\x00",
                    "Invalid SQLite header.", "invalid_database")
    harness.require(header[18:20] == b"\x01\x01", "Unsupported SQLite journal.", "unsupported_journal")
    with closing(engine.db_read(path)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        yield db


def _error(scope, exc):
    # Schema validation errors can contain excerpts from user-authored payloads.
    return f"{scope}读取失败（{getattr(exc, 'code', type(exc).__name__)}）"


def _runtime(path):
    with _read_db(path) as db:
        config = runtime.configuration(db)
        count = db.execute("SELECT count(*) FROM pending WHERE ack_request_id IS NULL").fetchone()[0]
        last = db.execute("SELECT created_at FROM events ORDER BY rowid DESC LIMIT 1").fetchone()
        return {"enabled": True, "pending_count": count, "latest_event": last[0] if last else None}, config


def _safe_ref(path):
    if not isinstance(path, str) or not path or len(path) > 500 or "\\" in path or ":" in path:
        return False
    return (not any(ord(c) < 32 for c in path)
            and all(p not in ("", ".", "..") and not runtime.protected(p)
                    and p.lower() not in {".codex", ".agents", ".dsh", ".config"} for p in path.split("/")))


def _history_entry(record):
    output = record["output"]
    details = []
    for key, label in LABELS.items():
        value = output.get(key)
        if isinstance(value, str) and value:
            details.append([label, value])
        elif key == "options" and isinstance(value, list):
            details.append([label, " / ".join(value)])
    for check in output.get("checks", []):
        details.append([check["check"], check["result"] + " · " + check["observation"]])
    refs = []
    for group, kind in (("candidate_files", "candidate"), ("evidence_files", "evidence")):
        for item in record.get(group, []):
            if _safe_ref(item["path"]):
                refs.append({"kind": kind, "path": item["path"],
                             "sha256": item["sha256"], "bytes": item["bytes"]})
    summary = next((output[key] for key in ("change", "proposal", "objection", "rationale", "observation",
                                            "outcome", "reason") if output.get(key)), "")
    return {"role": record["role"], "revision": record["revision"], "recorded_at": record["recorded_at"],
            "summary": summary, "details": details, "refs": refs}


def _steps(case, current):
    if case["route"] == "creation":
        roles = ["critic", "execution", "measurement"]
    elif case["route"] == "direct":
        roles = ["verifier"]
    else:
        evidence_role = "user_evidence" if case.get("task_stage") == "user_validation" else "verifier"
        roles = ["strategist", "critic", evidence_role, "judge"]
    completed = {item["role"] for item in case["history"]}
    position = roles.index(current) if current else len(roles)
    return [{"role": role, "status": "current" if role == current else
             "done" if index < position and role in completed else "upcoming"}
            for index, role in enumerate(roles)]


def _case(row, records, root, state, snapshot, verify_files):
    case = json.loads(row["initial"])
    case.update(history=records, superseded_by=row["superseded_by"])
    phase, role = engine.stage(case)
    harness.require((phase, role) == (row["phase"], row["next_role"]), "Inconsistent role state.", "invalid_case")
    stage = case.get("task_stage", "legacy_review")
    previous = json.loads(row["concern_context"])
    stale_concern = None
    if previous:
        cid = case.get("concern_id")
        current = engine.bound_concern(state, cid) if cid in state["concerns"] else None
        stale_concern = current is None or previous["digest"] != current["digest"]
    last_judge = records[-1]["output"] if records and records[-1]["role"] == "judge" else {}
    last_evidence = next((r for r in reversed(records) if r["role"] in ("user_evidence", "verifier")), {})
    observation = last_evidence.get("output", {})
    outcome = "unverified"
    if (case["mode"] == "live" and case["claim_type"] == "behavior" and phase != "superseded"
            and observation.get("method") == "human-task" and observation.get("provenance") == "human"
            and observation.get("finding") in {"supports", "refutes"} and last_evidence.get("evidence_files")):
        outcome = "observed_" + observation["finding"]
    return {
        "id": row["id"], "goal": case["goal"], "claim": case["claim"], "stage": stage, "mode": case["mode"],
        "phase": phase, "revision": row["revision"], "next_role": role, "superseded_by": row["superseded_by"],
        "user_evidence": {"create": "disabled", "user_validation": "enabled"}.get(stage, "not_applicable"),
        "user_outcome": outcome, "next_trigger": last_judge.get("next_trigger"), "outcome": last_judge.get("outcome"),
        "steps": _steps(case, role), "history": [_history_entry(r) for r in records],
        "integrity": engine.creative_integrity(case, root) if verify_files and stage == "create" else None,
        "stale_snapshot": None if snapshot is None else snapshot != row["snapshot"],
        "stale_concern": stale_concern, "updated_at": row["updated"],
    }


def _cases(path, root, state, snapshot, verify_files, issues):
    result = []
    with _read_db(path) as db:
        engine.identity(db, root, state["project"]["id"])
        rows = db.execute("""SELECT * FROM cases ORDER BY CASE phase WHEN 'active' THEN 0
            WHEN 'waiting_evidence' THEN 1 WHEN 'needs_owner' THEN 2 ELSE 3 END, updated DESC, id""")
        for row in rows:
            try:
                steps = db.execute("SELECT record FROM steps WHERE case_id=? ORDER BY rev", (row["id"],))
                records = [json.loads(step[0]) for step in steps]
                harness.require(len(records) + int(bool(row["superseded_by"])) == row["revision"],
                                "Incomplete role history.", "invalid_case")
                result.append(_case(row, records, root, state, snapshot, verify_files))
            except READ_ERRORS as exc:
                issues.append(_error("案件 " + row["id"], exc))
    return result


def _project(root, verify_files):
    project = {"root": str(root), "id": hashlib.sha256(str(root).encode()).hexdigest()[:24],
               "name": root.name, "goal": None, "status": "ready", "concerns": [], "cases": [],
               "runtime": {"enabled": False, "pending_count": None, "latest_event": None}}
    try:
        _, directory, state_path = harness.locations(root)
        runtime_path, engine_path = directory / runtime.DB_NAME, directory / engine.DB
        if not state_path.exists():
            leftovers = any(p.exists() or p.is_symlink() for p in (runtime_path, engine_path))
            project["status"] = "error" if leftovers else "not_initialized"
            if leftovers:
                project["error"] = "检测到数据库，但缺少对应的项目策略记录。"
            return project
        info = state_path.stat()
        state = _strategy(state_path, (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
        harness.require(state["project"]["root"] == str(root), "Project root mismatch.", "wrong_root")
        project.update(name=state["project"]["id"], goal=state["project"]["goal"],
                       concerns=[{"id": c["id"], "title": c["statement"], "status": c["status"]}
                                 for c in state["concerns"].values()])
    except READ_ERRORS as exc:
        project["runtime"]["enabled"] = None
        project.update(status="error", error=_error("项目策略", exc))
        return project
    issues = []
    snapshot = None
    config = None
    if runtime_path.exists() or runtime_path.is_symlink():
        try:
            project["runtime"], config = _runtime(runtime_path)
        except READ_ERRORS as exc:
            project["runtime"]["enabled"] = None
            issues.append(_error("执行状态", exc))
    if engine_path.exists() or engine_path.is_symlink():
        if project["runtime"]["enabled"] is False:
            issues.append("案件存在，但项目执行层配置缺失。")
        if verify_files and config:
            try:
                snapshot = runtime.snapshot(root, config)
            except READ_ERRORS as exc:
                issues.append(_error("观察范围", exc))
        try:
            project["cases"] = _cases(engine_path, root, state, snapshot, verify_files, issues)
        except READ_ERRORS as exc:
            issues.append(_error("角色案件", exc))
    if issues:
        project.update(status="partial", error="；".join(issues))
    return project


def build_snapshot(roots, verify_files=False):
    """Read each selected project once. File hashing is opt-in for explicit verification."""
    projects = [_project(root, verify_files) for root in dict.fromkeys(Path(p).expanduser().resolve() for p in roots)]
    return {"generated_at": harness.now(), "projects": projects}
