#!/usr/bin/env python3
"""Run an isolated creation, artifact check, or simulated user validation through the role CLI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent


def call(root, script, command, payload=None, extra=()):
    args = [sys.executable, str(SCRIPTS / script), command, "--root", str(root), *extra]
    run = subprocess.run(args, input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                         capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(f"{script} {command}: {run.stdout.strip()} {run.stderr.strip()}")
    result = json.loads(run.stdout)
    if not result.get("ok"):
        raise RuntimeError(str(result))
    return result


def validation_demo(root):
    root = root.absolute()
    root.mkdir(parents=True, exist_ok=False)
    (root / "src").mkdir()
    (root / "evidence").mkdir()
    (root / "src" / "card.html").write_text('<article><button>Save for later</button></article>\n', encoding="utf-8")
    goal = "让读者顺利保留稍后想读的文章，同时保持列表安静。"
    claim = "读者能在现有入口独立完成稍后读，无需额外寻找入口。"
    call(root, "harness.py", "init", extra=("--project-id", "reading-list-fixture", "--goal", goal,
                                             "--scope", "Synthetic example only", "--version", "demo-v1"))
    call(root, "runtime.py", "setup", extra=("--watch", "src/**"))
    for k, v in {"supports": "模拟情境：读者按其阅读顺序独立完成保存。",
                 "refutes": "模拟情境：已有保存意图；在列表反复寻找，最终需要提示。",
                 "screen": "示例界面有 Save for later 控件。没有人参与这次演示。"}.items():
        (root / "evidence" / (k + ".txt")).write_text(v + "\n", encoding="utf-8")
    log = []

    def op(action, payload):
        view = call(root, "engine.py", action, payload)
        log.append({"case_id": view["case_id"], "action": action, "role": payload.get("role"),
                    "revision": view["revision"], "phase": view["phase"], "next_role": view["next_role"],
                    "output": payload.get("output"), "fixture": True})
        return view

    def submit(v, role, output):
        if v["next_role"] != role:
            raise RuntimeError("Unexpected next role: " + str(v["next_role"]))
        return op("submit", {"case_id": v["case_id"], "binding": v["binding"], "expected_revision": v["revision"],
                             "request_id": f"{v['case_id']}-{v['revision']}-{role}", "role": role, "output": output})

    def verify(kind):
        if kind == "screen":
            return {"method":"artifact-check","provenance":"artifact","finding":"inconclusive",
                    "observation":"示例中存在收藏控件，没有用户操作记录。","scope":"单个示例页面",
                    "evidence_refs":["evidence/screen.txt"],"limitations":"无法观察人的发现过程。"}
        return {"method":"human-task","provenance":"simulation","finding":kind,
                "task":"把一篇现在没空看的文章留到稍后。","participant_scope":"受控脚本分支，无真实参与者。",
                "observation": (root / "evidence" / (kind+".txt")).read_text(encoding="utf-8").strip(),
                "scope":"同一虚构版本及任务，仅用于检验路由。","evidence_refs":["evidence/"+kind+".txt"],
                "limitations":"模拟材料不是用户证据，不能写回任何产品成效。"}

    def judge(outcome):
        detail = {
          "keep": ("模拟支持原主张，暂时维持原方案。","异议合理，但脚本分支没有出现需提示的障碍。"),
          "revise": ("模拟反例推翻了独立完成假设，建议局部试验显式入口。","采纳异议：用户有意图却找不到入口。"),
          "defer": ("材料只能说明元素存在，无法裁决用户行为。","保留异议，等待独立完成任务的记录。")}[outcome]
        return {"outcome":outcome, "rationale":detail[0],"critic_response":detail[1],
                "tradeoff":"显式入口可能提高可发现性，但增加列表噪音。","next_trigger":"取得新的无提示任务观察或设计版本改变时复查。"}

    final = {}
    for kind, verdict in [("supports","keep"),("refutes","revise"),("screen","defer")]:
        cid = "card-"+kind
        v = op("open",{"case_id":cid,"goal":goal,"claim":claim,"claim_type":"behavior","mode":"fixture","task_stage":"user_validation"})
        v = submit(v,"strategist",{"intent":goal,"options":["保持安静的当前入口","在列表常驻保存入口"],
                   "proposal":"保持安静的当前入口","assumption":claim,"reopen_if":"已有保存意图却要靠提示才能完成。"})
        v = submit(v,"critic",{"objection":"第一次在列表做取舍的人可能看不到保存入口。","consequence":"已经决定稍后读，却被迫中断浏览。",
                   "check":"给保留文章的任务，不提示按钮；记录第一动作及是否需要帮助。","reason":"卡片看起来整齐不能证明入口能被发现。"})
        v = submit(v,"user_evidence",verify(kind))
        v = submit(v,"judge",judge(verdict))
        final[cid] = (v["phase"], verdict)
        if kind == "screen":
            assert v["phase"] == "waiting_evidence"
            # Read in a new CLI process: lack of evidence does not cause a model loop.
            restored = call(root,"engine.py","context",extra=("--case-id",cid))
            assert restored["next_role"] is None and restored["phase"] == "waiting_evidence"
            v = op("resume",{"case_id":cid,"expected_revision":v["revision"],"binding":v["binding"],
                             "request_id":"screen-followup", "reason":"演示现在另行提供模拟反例，之前的等待保留在历史里。"})
            v = submit(v,"user_evidence",verify("refutes"))
            v = submit(v,"judge",judge("revise"))
            final[cid] = (v["phase"], "defer → resume → revise")

    (root/"TRACE.json").write_text(json.dumps(log, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    (root/"RESULTS.md").write_text("# 角色流程演示 · 全部为 fixture\n\n三个分支共享同一用户主张。模拟数据只检验程序分支。\n\n"
        +"| 案例 | 最终阶段 | 裁决轨迹 |\n|---|---|---|\n"
        +"".join(f"| {key} | {phase} | {outcome} |\n" for key,(phase,outcome) in final.items())
        +"\nTRACE.json 保存每次角色输出、阶段和修订号。真实产品未做任何变更。\n",encoding="utf-8")
    return {"ok":True, "mode":"fixture","cases":final,"trace":str(root/"TRACE.json"),"report":str(root/"RESULTS.md")}



def artifact_demo(root, task_stage):
    from html.parser import HTMLParser

    class SaveControl(HTMLParser):
        def __init__(self):
            super().__init__()
            self.checkbox = None
            self.label_target = None
            self.disclosures = 0
            self.behind_disclosure = False

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "details":
                self.disclosures += 1
            elif tag == "input" and attributes.get("type") == "checkbox":
                self.checkbox = attributes.get("id")
                self.behind_disclosure = self.disclosures > 0
            elif tag == "label":
                self.label_target = attributes.get("for")

        def handle_endtag(self, tag):
            if tag == "details":
                self.disclosures -= 1

    root = root.absolute()
    root.mkdir(parents=True, exist_ok=False)
    (root / "baseline").mkdir()
    (root / "checks").mkdir()
    article = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>阅读列表</title><style>body{font:18px system-ui;max-width:42rem;margin:10vh auto;padding:1em}
label,summary,input{cursor:pointer}label{padding:.4em}small{color:#555}</style>
<main><h1>阅读列表</h1><article><small>编辑部 · 周二</small><h2>河岸步行笔记</h2>
%s</article></main></html>"""
    control = '<input id="save" type="checkbox"><label for="save">稍后读</label>'
    baseline_ref = "baseline/card.html"
    (root / baseline_ref).write_text(article % ("<details><summary>文章操作</summary>" + control + "</details>"), encoding="utf-8")
    call(root, "harness.py", "init", extra=("--project-id","reading-artifact","--goal","让读者在列表中保留稍后阅读的文章",
                                            "--scope","Generic editable fixture","--version","v1"))
    call(root, "runtime.py", "setup", extra=("--watch","baseline/**"))
    view = call(root, "engine.py", "open", {"case_id":"save-control", "goal":"在列表内保存文章",
                "claim":"候选页面的稍后读控件在默认文档结构中有显式入口。" if task_stage == "create" else "原版文档包含关联标签的保存控件。",
                "claim_type":"artifact", "mode":"fixture", "task_stage":task_stage})
    trace = []

    def submit(role, output):
        nonlocal view
        if view["next_role"] != role:
            raise RuntimeError("Unexpected next role: " + str(view["next_role"]))
        view = call(root, "engine.py", "submit", {"case_id":view["case_id"],"binding":view["binding"],
                    "expected_revision":view["revision"],"request_id":"demo-" + str(view["revision"]),
                    "role":role,"output":output})
        trace.append({"role":role,"revision":view["revision"],"phase":view["phase"],"output":output})

    target = baseline_ref
    if task_stage == "create":
        submit("critic", {"change":"将原版折叠菜单中的稍后读操作移到文章标题下。","tradeoff":"多一个常显控件，占用一行空间。",
                          "acceptance":"同一篇文章保留原文；保存控件有明确标签，且位于折叠菜单外。"})
        target = view["candidate_dir"] + "/card.html"
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        (root / target).write_text(article % control, encoding="utf-8")
        submit("execution", {"change":"已生成可打开并切换稍后读的候选页面。","candidate_refs":[target],
                             "review_steps":"打开原版与候选 HTML，比较展开前后的控件；点选或用空格切换复选框。"})
    markup = SaveControl()
    markup.feed((root / target).read_text(encoding="utf-8"))
    checks = [{"check":"checkbox has an associated label",
               "result":"pass" if markup.checkbox and markup.checkbox == markup.label_target else "fail",
               "observation":f"checkbox={markup.checkbox}, label.for={markup.label_target}"}]
    if task_stage == "create":
        checks.append({"check":"save control outside disclosure","result":"fail" if markup.behind_disclosure else "pass",
                       "observation":"inside details: " + str(markup.behind_disclosure)})
    passed = all(c["result"] == "pass" for c in checks)
    proof = "checks/markup.json"
    limit = "HTML 解析只检查文档结构。浏览器布局、读者操作和长期保存均未经本例测量。"
    (root / proof).write_text(json.dumps({"artifact":target,"checks":checks,"limits":limit}, ensure_ascii=False,indent=2)+"\n", encoding="utf-8")
    if task_stage == "create":
        submit("measurement", {"outcome":"ready" if passed else "rework","checks":checks,"evidence_refs":[proof],"limitations":limit})
    else:
        submit("verifier", {"method":"artifact-check","provenance":"artifact","finding":"supports" if passed else "refutes",
                            "observation":checks[0]["observation"],"scope":target,"evidence_refs":[proof],"limitations":limit})
    (root / "TRACE.json").write_text(json.dumps(trace,ensure_ascii=False,indent=2)+"\n", encoding="utf-8")
    summary = (f"# 阅读卡片演示\n\n阶段 `{task_stage}`，结果 `{view['phase']}`。\n\n"
               f"[原版]({baseline_ref}) · [检查对象]({target}) · [实测记录]({proof}) · [角色交付](TRACE.json)\n\n"
               + limit + " 本例没有参与者。\n")
    (root / "RESULTS.md").write_text(summary, encoding="utf-8")
    return {"ok":passed,"task_stage":task_stage,"phase":view["phase"],"artifact":str(root/target),
            "report":str(root/"RESULTS.md"),"user_outcome":"unverified"}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=("create","artifact_check","user_validation"), default="create")
    p.add_argument("--output",type=Path,required=True,help="A new folder; never overwrites an existing project.")
    args=p.parse_args()
    try:
        result = validation_demo(args.output) if args.stage == "user_validation" else artifact_demo(args.output, args.stage)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            sys.exit(1)
    except (OSError,RuntimeError) as exc: p.exit(1, str(exc)+"\n")
