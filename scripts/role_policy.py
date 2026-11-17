"""Host-executed role contracts; deterministic routing, no model or filesystem IO.

The kernel owns the event history, revision, project/snapshot binding and the
contents/hash of evidence files. This module only checks order, declared
provenance/method and output contracts. It cannot authenticate a human, inspect
an artifact or establish that a written claim is true.
"""
import copy
from pathlib import PurePosixPath, PureWindowsPath


ROLE_CARDS = {
    "strategist": {
        "question": "这个用户在这个旅程中要做什么？哪一种可推翻的取舍值得验证？",
        "inputs": ["项目目标与授权范围", "本案的主张、工件版本、历史决定"],
        "outputs": ["意图", "至少两个不同选择（包括维持现状，如适用）", "提案", "关键假设", "改判条件"],
        "authority": "可以提出维持或改变的方案。",
        "limits": "不能代替用户确定产品目标，不能将提案写成已实现或已验收。",
    },
    "critic": {
        "question": "在哪个具体情境下，这个方案会失败或损害另一项目标？",
        "inputs": ["策略师的提案与假设", "当前旅程、版本和已有证据"],
        "outputs": ["一个可能改变决定的异议（或明确无实质异议）", "后果", "区分两种解释的方法", "依据"],
        "authority": "可以挑战提案和验证方式；没有新的实质异议时允许不反对。",
        "limits": "不能仅凭批评否决方案，也不能伪造用户反应。",
    },
    "verifier": {
        "question": "实际观察到了什么？这种方法足以回答本案的哪项主张？",
        "inputs": ["待验收的确切主张、当前快照及范围", "异议和可区分解释的观察任务"],
        "outputs": ["方法与来源", "支持/反驳/不确定/未取得", "可复核材料", "适用范围与限制"],
        "authority": "可以记录事实或说明无法获得证据；只能使用已获准的材料和工具。",
        "limits": "不能用截图或模型推测冒充真人任务，不能自行采纳设计、发版或关闭策略问题。",
    },
    "judge": {
        "question": "在这个目标、版本、证据范围内，采取哪个决定？什么会导致改判？",
        "inputs": ["提案", "Critic 的异议或其未提异议的理由", "Verifier 的观测与局限"],
        "outputs": ["维持/修订/撤回/等待/交负责人", "回应异议", "接受的代价", "重开条件"],
        "authority": "可以在原授权范围内作出策略裁决，包括拒绝一条有道理但不改变选择的批评。",
        "limits": "不能改写观测、替产品负责人选择冲突目标、执行发布，或把决策当作人类接受。",
    },
}

CREATE_CRITIC = {
    "question": "当前设计意图值得尝试哪一个小而可逆的改变？",
    "inputs": ["本次意图与现有产物", "已有约束、已知摩擦与设计取舍"],
    "outputs": ["具体改变", "接受的取舍", "能在产物上检查的验收条件"],
    "authority": "为这一轮选择一个候选方案，交给 Execution 实际制作。",
    "limits": "保留用户行为假设；创作阶段不招募参与者，不以缺少用户阻断制作。",
}
ROLE_CARDS.update({
    "execution": {
        "question": "这一轮实际做出了哪个可检查的候选？怎样打开或比对？",
        "inputs": ["Critic 确定的改变、取舍与验收条件", "当前产品版本", "若返工，读取上次检查失败的原因"],
        "outputs": ["已实现的改变", "项目内新候选文件", "打开、操作或比对方法"],
        "authority": "按已授权范围制作可撤回的候选版本，保留原产品。",
        "limits": "仅提交工单或计划不能完成此角色；不替用户确认体验效果。",
    },
    "measurement": {
        "question": "在该候选的这个版本、状态和操作下，哪些验收条件实际成立？",
        "inputs": ["本次候选及指纹", "Critic 的验收条件", "实际观察、操作或渲染记录"],
        "outputs": ["逐项检查和观测结果", "实际检查证据", "局限", "候选就绪或返工"],
        "authority": "检查产物，记录本次范围并决定候选是否需要返工。",
        "limits": "仅作产物判断。User Evidence 保持关闭；用户效果仍为未验证。",
    },
    "user_evidence": {
        "question": "真实使用者在本版本、这个任务下做了什么？无数据时还缺什么？",
        "inputs": ["明确的用户验证任务、主张与异议", "获授权的匿名用户任务材料"],
        "outputs": ["实际来源和任务", "观察结果或尚缺观察", "可复核引用、适用范围和限制"],
        "authority": "在明确的用户验证阶段记录证据与缺口；按问题确定方法及参与范围。",
        "limits": "不预设样本数，不招募未经授权的参与者，不从原型检查推断行为改善。",
    },
})


def role_card(role, task_stage=None):
    card = CREATE_CRITIC if role == "critic" and task_stage == "create" else ROLE_CARDS[role]
    return copy.deepcopy(card)


_TEMPLATES = {
    "strategist": {
        "intent": "[[用户任务与设计意图]]", "options": ["[[保留当前行为]]", "[[另一个可行方案]]"],
        "proposal": "[[所选方案]]", "assumption": "[[选择这个方案依赖的关键假设]]",
        "reopen_if": "[[哪种观察会改变决定]]",
    },
    "critic": {
        "objection": None, "consequence": None, "check": "[[区分解释的检查或维持原验证计划的理由]]",
        "reason": "[[提出异议或没有实质异议的具体理由]]",
    },
    "verifier": {
        "method": "artifact-check", "provenance": "none", "finding": "unavailable",
        "observation": "[[记录实际观察；不能执行时写明原因]]", "scope": "[[本次任务、版本、状态与范围]]",
        "evidence_refs": [], "limitations": "[[未确认事项或限制]]",
    },
    "judge": {
        "outcome": "defer", "rationale": "[[这个结论如何由观察支持；证据不足时为什么等待]]",
        "critic_response": "[[具体采纳或拒绝哪条异议以及为什么，或说明无实质异议]]",
        "tradeoff": "[[接受的代价或仍待选择的冲突]]", "next_trigger": "[[再验证的条件或下一行动]]",
    },
}
_CREATE_OUTPUTS = {
    "critic": {"change": "[[这一轮要做的可逆改变]]", "tradeoff": "[[选择的代价]]",
               "acceptance": "[[可以在候选产物上检查的验收条件]]"},
    "execution": {"change": "[[实际完成的改变]]", "candidate_refs": ["[[candidate_dir 下的候选入口文件]]"],
                  "review_steps": "[[如何打开、操作或比对候选]]"},
    "measurement": {"outcome": "ready", "checks": [{"check": "[[检查条件]]", "result": "pass",
                    "observation": "[[实际执行的检查和观察]]"}], "evidence_refs": ["[[检查记录的相对路径]]"],
                    "limitations": "[[本轮产物检查尚未覆盖的事项]]"},
}
_METHODS = {"artifact-check", "human-task", "agent-review"}
_SOURCES = {"artifact", "human", "simulation", "none"}
_FINDINGS = {"supports", "refutes", "inconclusive", "unavailable"}
_JUDGMENTS = {"keep", "revise", "withdraw", "defer", "escalate"}
_CONCLUSIVE = {"supports", "refutes"}
_LIMIT = 4000


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > _LIMIT:
        raise ValueError(field + " must be nonempty text (max 4000 characters)")
    if "[[" in value or "]]" in value:
        raise ValueError(field + ": replace the template placeholder with an actual answer")


def _enum(value, choices, field):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(field + " must be one of: " + ", ".join(sorted(choices)))


def _keys(value, fields, optional=()):
    if not isinstance(value, dict):
        raise ValueError("role output must be an object")
    missing = set(fields) - value.keys()
    extra = set(value) - set(fields) - set(optional)
    if missing or extra:
        raise ValueError("role output field mismatch: missing=" + str(sorted(missing))
                         + ", unknown=" + str(sorted(extra)))


def _refs(refs):
    if not isinstance(refs, list) or len(refs) > 16:
        raise ValueError("evidence_refs must be a list of up to 16 relative file paths")
    for ref in refs:
        _text(ref, "evidence_refs item")
        # Do not turn remote URLs, absolute paths or '.'/'..' into a file in
        # some other directory. Kernel independently verifies the actual file.
        if ("\\" in ref or ":" in ref or "\x00" in ref or ref != ref.strip()
                or any(ord(char) < 32 for char in ref)
                or PurePosixPath(ref).is_absolute() or PureWindowsPath(ref).drive
                or any(part in ("", ".", "..") for part in ref.split("/"))):
            raise ValueError("evidence_refs must use project-relative paths without traversal")
    if len(set(refs)) != len(refs):
        raise ValueError("evidence_refs contains a duplicate")


def choose_route(claim_type, signals=None, requested=None, task_stage=None):
    """Deterministic choice at intake; human or host declares observable signals."""
    _enum(claim_type, {"artifact", "behavior"}, "claim_type")
    if signals is None:
        signals = []
    if not isinstance(signals, list) or len(signals) > 3:
        raise ValueError("signals must be a list of unique routing signals")
    for signal in signals:
        _enum(signal, {"tradeoff", "counterevidence", "high-rework"}, "signal")
    if len(set(signals)) != len(signals):
        raise ValueError("duplicate routing signal")
    if task_stage is not None:
        _enum(task_stage, {"create", "artifact_check", "user_validation"}, "task_stage")
        route = {"create": "creation", "artifact_check": "direct", "user_validation": "tradeoff"}[task_stage]
        if task_stage == "artifact_check" and claim_type != "artifact":
            raise ValueError("artifact_check requires an artifact claim")
        if task_stage == "user_validation" and claim_type != "behavior":
            raise ValueError("user_validation requires a behavior claim")
        if requested is not None and requested != route:
            raise ValueError("requested route conflicts with this task_stage")
        return route
    required = "tradeoff" if claim_type == "behavior" or signals else "direct"
    if requested is not None:
        _enum(requested, {"direct", "tradeoff"}, "requested route")
        if requested == "direct" and required == "tradeoff":
            raise ValueError("claim or risk signals require the tradeoff route")
    return requested or required


def _case_shape(case):
    if not isinstance(case, dict) or not isinstance(case.get("history"), list):
        raise ValueError("case must provide a history list")
    _enum(case.get("route"), {"tradeoff", "direct", "creation"}, "route")
    if (case["route"] == "creation") != (case.get("task_stage") == "create"):
        raise ValueError("the creation route requires task_stage=create")
    _enum(case.get("claim_type"), {"artifact", "behavior"}, "claim_type")
    if case["route"] == "direct" and case["claim_type"] != "artifact":
        raise ValueError("a behavior claim requires the tradeoff route, not direct verification")


def _eligible(case, v):
    if v["finding"] not in _CONCLUSIVE or not v["evidence_refs"]:
        return False
    simulated = v["provenance"] == "simulation" and case.get("mode") == "fixture"
    if case["claim_type"] == "behavior":
        return (v["method"] == "human-task" and (v["provenance"] == "human" or simulated)
                and bool(v.get("task")) and bool(v.get("participant_scope")))
    return v["method"] == "artifact-check" and (v["provenance"] == "artifact" or simulated)


def _position(case):
    """Compute position from kernel-validated transitions; never call a model."""
    _case_shape(case)
    h = case["history"]
    evidence_role = "user_evidence" if case.get("task_stage") == "user_validation" else "verifier"
    if case["route"] == "creation":
        if not h:
            return "active", "critic"
        last = h[-1]
        if last["role"] == "critic":
            return "active", "execution"
        if last["role"] == "execution":
            return "active", "measurement"
        if last["role"] == "measurement":
            if last["output"]["outcome"] == "rework":
                return "active", "execution"
            if last["output"]["outcome"] == "ready":
                return "candidate_ready", None
        raise ValueError("invalid creative role history")
    if not h:
        return "active", "strategist" if case["route"] == "tradeoff" else "verifier"
    entry = h[-1]
    if not isinstance(entry, dict) or not isinstance(entry.get("output"), dict):
        raise ValueError("invalid role history entry")
    role, out = entry.get("role"), entry["output"]
    if role == "resume":
        return "active", evidence_role
    if role == "strategist":
        return "active", "critic"
    if role == "critic":
        return "active", evidence_role
    if role == evidence_role:
        if case["route"] == "tradeoff":
            return "active", "judge"
        if not _eligible(case, out):
            return "waiting_evidence", None
        if out["finding"] == "supports":
            return "verified", None
        return "needs_owner", None  # The artifact contradicted the claim.
    if role == "judge":
        if out.get("outcome") == "defer":
            return "waiting_evidence", None
        if out.get("outcome") == "escalate":
            return "needs_owner", None
        if out.get("outcome") in {"keep", "revise", "withdraw"}:
            return "decided", None
    raise ValueError("invalid role or judgment in history")


def next_role(case):
    return _position(case)[1]


def phase(case):
    return _position(case)[0]


def role_brief(case):
    current_phase, role = _position(case)
    creative = case.get("task_stage") == "create"
    instructions = {
        "active": "仅承担当前角色。主张是本案固定的待验命题；supports/refutes 针对它，而非整体产品好坏。改变命题应另开案件。",
        "waiting_evidence": "保留未决问题。得到新材料后显式恢复，由验证者重新观察；不自动重复执行。",
        "decided": "保存裁决理由、取舍和下次触发条件。作出决定不代表产品已实施、已发布或用户认可。",
        "needs_owner": "需负责人接手；查看反证或目标冲突，保留原观察。本状态不代表验收通过。",
        "candidate_ready": "候选已完成本轮产物检查。用户效果保持未验证；产品采纳由原项目另行决定。",
        "verified": "只在记录的工件版本、场景和范围内通过。没有作出产品效果或用户接受判断。",
    }[current_phase]
    if creative and current_phase == "active":
        instructions = ("按当前角色推进创作。新文件放在 candidate_dir 中，候选及检查证据应在产品 watch 范围外。"
                        "检查版本变化需重新交付。尚无用户时正常创作，用户效果保持未验证。")
    if case.get("mode") == "fixture":
        instructions += " 本案是受控模拟，所有结果只能用于演练流程，不能作为实际用户或产品效果证据。"
    templates = _CREATE_OUTPUTS if creative else _TEMPLATES
    template = copy.deepcopy(templates["verifier" if role == "user_evidence" else role]) if role else None
    if role in {"verifier", "user_evidence"}:
        instructions += (" finding 为 supports/refutes 时须附本项目相对路径。没有可用证据用 "
                         "unavailable + none + []。未能回答主张的截图可记录为 inconclusive。")
        if case["claim_type"] == "behavior":
            template["method"] = "human-task"
            instructions += (" 真正的行为验证需填写 task 与 participant_scope（匿名范围），"
                             "声明 human-task + human，或在模拟案中明确 simulation。")
    if role == "judge":
        instructions += " 观察不足只能 defer/escalate；关键假设已被反驳，不能原样 keep。越权的价值冲突交负责人。"
    values = {}
    if role in {"verifier", "user_evidence"}:
        sources = _SOURCES if case.get("mode") == "fixture" else _SOURCES - {"simulation"}
        values = {"method": sorted(_METHODS), "provenance": sorted(sources),
                  "finding": sorted(_FINDINGS), "evidence_refs": "0–16 project-relative file paths"}
    elif role == "measurement":
        values = {"outcome": ["ready", "rework"], "result": ["pass", "fail"]}
    elif role == "judge":
        observed = case["history"][-1]["output"]
        allowed = set(_JUDGMENTS)
        if not _eligible(case, observed):
            allowed = {"defer", "escalate"}
        elif observed["finding"] == "refutes":
            allowed.discard("keep")
        values = {"outcome": sorted(allowed)}
    return {"phase": current_phase, "role": role, "values": values,
            "contract": role_card(role, case.get("task_stage")) if role else None,
            "template": template, "instructions": instructions}


def _validate_creative(role, output):
    _keys(output, _CREATE_OUTPUTS[role])
    if role == "critic":
        for field in ("change", "tradeoff", "acceptance"):
            _text(output[field], field)
    elif role == "execution":
        _text(output["change"], "change")
        _text(output["review_steps"], "review_steps")
        _refs(output["candidate_refs"])
        if not output["candidate_refs"]:
            raise ValueError("execution requires at least one actual candidate file")
    else:
        _enum(output["outcome"], {"ready", "rework"}, "outcome")
        _text(output["limitations"], "limitations")
        _refs(output["evidence_refs"])
        if not output["evidence_refs"]:
            raise ValueError("measurement requires actual check evidence")
        checks = output["checks"]
        if not isinstance(checks, list) or not 1 <= len(checks) <= 32:
            raise ValueError("record 1 to 32 executed artifact checks")
        for check in checks:
            _keys(check, ("check", "result", "observation"))
            _text(check["check"], "check")
            _text(check["observation"], "observation")
            _enum(check["result"], {"pass", "fail"}, "check.result")
        if output["outcome"] == "ready" and any(c["result"] == "fail" for c in checks):
            raise ValueError("a failed acceptance check requires rework")


def validate_output(case, role, output):
    """Validate an output for the current role; no state mutation or IO."""
    expected = next_role(case)
    if not isinstance(role, str) or role not in ROLE_CARDS or role != expected:
        raise ValueError("wrong role or inactive case: expected " + str(expected))
    if case.get("task_stage") == "create":
        return _validate_creative(role, output)
    if role == "strategist":
        _keys(output, _TEMPLATES[role])
        for field in ("intent", "proposal", "assumption", "reopen_if"):
            _text(output[field], field)
        options = output["options"]
        if not isinstance(options, list) or not 2 <= len(options) <= 8:
            raise ValueError("options must contain 2 to 8 distinct choices")
        for option in options:
            _text(option, "option")
        if len({opt.strip().casefold() for opt in options}) != len(options):
            raise ValueError("options must be distinct")
    elif role == "critic":
        _keys(output, _TEMPLATES[role])
        _text(output["check"], "check")
        _text(output["reason"], "reason")
        if output["objection"] is None:
            if output["consequence"] is not None:
                raise ValueError("without an objection use null for consequence")
        else:
            _text(output["objection"], "objection")
            _text(output["consequence"], "consequence")
    elif role in {"verifier", "user_evidence"}:
        _keys(output, _TEMPLATES["verifier"], ("task", "participant_scope"))
        for field in ("scope", "observation", "limitations"):
            _text(output[field], field)
        for field in ("task", "participant_scope"):
            if field in output:
                _text(output[field], field)
        method, source, finding = (output[f] for f in ("method", "provenance", "finding"))
        _enum(method, _METHODS, "method")
        _enum(source, _SOURCES, "provenance")
        _enum(finding, _FINDINGS, "finding")
        _refs(output["evidence_refs"])
        if finding == "unavailable":
            if source != "none" or output["evidence_refs"]:
                raise ValueError("unavailable requires provenance none and no evidence_refs")
            return
        if source == "none" or not output["evidence_refs"]:
            raise ValueError("an observation requires evidence_refs and a declared source")
        if source == "simulation" and case.get("mode") != "fixture":
            raise ValueError("simulation is restricted to explicitly marked fixture cases")
        if (source == "human") != (method == "human-task") and source != "simulation":
            raise ValueError("human provenance and human-task method must be paired")
        if finding in _CONCLUSIVE and not _eligible(case, output):
            raise ValueError("method/source cannot determine this claim; record inconclusive or obtain matching evidence")
    else:
        _keys(output, _TEMPLATES[role])
        _enum(output["outcome"], _JUDGMENTS, "outcome")
        for field in ("rationale", "critic_response", "tradeoff", "next_trigger"):
            _text(output[field], field)
        verifier = case["history"][-1]["output"]
        if not _eligible(case, verifier) and output["outcome"] not in {"defer", "escalate"}:
            raise ValueError("insufficient matching evidence: judge must defer or escalate")
        if verifier["finding"] == "refutes" and output["outcome"] == "keep":
            raise ValueError("the stated assumption was refuted: revise, withdraw, defer, or escalate")
