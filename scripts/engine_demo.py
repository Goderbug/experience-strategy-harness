#!/usr/bin/env python3
"""Run the role-engine CLI on a fresh, explicitly simulated project. No model or network."""
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


def execute(root):
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
        v = op("open",{"case_id":cid,"goal":goal,"claim":claim,"claim_type":"behavior","mode":"fixture"})
        v = submit(v,"strategist",{"intent":goal,"options":["保持安静的当前入口","在列表常驻保存入口"],
                   "proposal":"保持安静的当前入口","assumption":claim,"reopen_if":"已有保存意图却要靠提示才能完成。"})
        v = submit(v,"critic",{"objection":"第一次在列表做取舍的人可能看不到保存入口。","consequence":"已经决定稍后读，却被迫中断浏览。",
                   "check":"给保留文章的任务，不提示按钮；记录第一动作及是否需要帮助。","reason":"卡片看起来整齐不能证明入口能被发现。"})
        v = submit(v,"verifier",verify(kind))
        v = submit(v,"judge",judge(verdict))
        final[cid] = (v["phase"], verdict)
        if kind == "screen":
            assert v["phase"] == "waiting_evidence"
            # Read in a new CLI process: lack of evidence does not cause a model loop.
            restored = call(root,"engine.py","context",extra=("--case-id",cid))
            assert restored["next_role"] is None and restored["phase"] == "waiting_evidence"
            v = op("resume",{"case_id":cid,"expected_revision":v["revision"],"binding":v["binding"],
                             "request_id":"screen-followup", "reason":"演示现在另行提供模拟反例，之前的等待保留在历史里。"})
            v = submit(v,"verifier",verify("refutes"))
            v = submit(v,"judge",judge("revise"))
            final[cid] = (v["phase"], "defer → resume → revise")

    v = op("open",{"case_id":"element-present","goal":"验证静态模板中的按钮。","claim":"示例模板含 Save for later 按钮。",
                   "claim_type":"artifact","mode":"fixture"})
    from html.parser import HTMLParser
    class ButtonText(HTMLParser):
        active = False
        def __init__(self):
            super().__init__()
            self.captions = []
        def handle_starttag(self, tag, attrs):
            if tag == "button": self.active = True
        def handle_endtag(self, tag):
            if tag == "button": self.active = False
        def handle_data(self, data):
            if self.active: self.captions.append(data.strip())
    parser = ButtonText()
    parser.feed((root/"src/card.html").read_text(encoding="utf-8"))
    assert "Save for later" in parser.captions
    v=submit(v,"verifier",{"method":"artifact-check","provenance":"artifact","finding":"supports",
              "observation":"HTML parser found the Save for later button in the fixture template.","scope":"Static markup only.",
              "evidence_refs":["src/card.html"],"limitations":"Does not establish rendering, keyboard behavior or discoverability."})
    assert v["phase"] == "verified"
    final[v["case_id"]] = (v["phase"], "verifier only")
    (root/"TRACE.json").write_text(json.dumps(log, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    (root/"RESULTS.md").write_text("# 角色流程演示 · 全部为 fixture\n\n三个分支共享同一用户主张。模拟数据只检验程序分支。\n\n"
        +"| 案例 | 最终阶段 | 裁决轨迹 |\n|---|---|---|\n"
        +"".join(f"| {key} | {phase} | {outcome} |\n" for key,(phase,outcome) in final.items())
        +"\nTRACE.json 保存每次角色输出、阶段和修订号。真实产品未做任何变更。\n",encoding="utf-8")
    return {"ok":True, "mode":"fixture","cases":final,"trace":str(root/"TRACE.json"),"report":str(root/"RESULTS.md")}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True,help="A new folder; never overwrites an existing project.")
    args=p.parse_args()
    try: print(json.dumps(execute(args.output),ensure_ascii=False,indent=2))
    except (OSError,RuntimeError) as exc: p.exit(1, str(exc)+"\n")
