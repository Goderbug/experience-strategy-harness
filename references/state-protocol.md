# 状态与调用协议 · 0.1.0

## 运行边界

宿主负责体验判断、观察产品、执行当前范围内的任务，以及决定节点何时发生。脚本负责可恢复记录，不会运行模型、读取任意产品数据或订阅外部变化。`online:false` 和 `background_monitoring:false` 表示没有后台观察进程。

本 MVP 采用一个项目一个写入者。若多个 Agent 同时参与，其他 Agent 返回带来源的发现，由当前写入者合并。记录中的 actor/origin 是来源声明，不是身份认证。

## 命令

```text
python3 scripts/harness.py init --root PATH --project-id ID --goal TEXT --scope TEXT --version LABEL [--mode analysis-only|prototype|implementation]
python3 scripts/harness.py context --root PATH
python3 scripts/harness.py commit --root PATH --input CHECKPOINT_JSON
python3 scripts/harness.py commit --root PATH --input -
python3 scripts/harness.py validate --root PATH
python3 scripts/harness.py export --root PATH --output NEW_DIRECTORY
```

PATH 是现有项目目录。只有 `.experience-strategy/` 内的记录由脚本管理，不能用初始化覆盖已有记录。`--input -` 从标准输入读取 JSON；无需将用户文本拼接进 shell 命令。

`init` 的默认 mode 为 `analysis-only`。mode 记录当前工作范围，不会授予实施或发布权限。已有授权和新指令以用户实际请求为准。

`context` 读取状态和节点记录；新 Agent 先读它，再决定本轮相关内容。每次 commit 之前使用最新 revision。MVP 项目较小时可以读取完整状态；对长记录，只把目标、相关问题、历史取舍、证据和最近节点放入工作上下文。

`export` 写入一个新的目录，生成 state.json、checkpoints.jsonl 和 RETURN-REPORT.md 提纲。用包内 templates/RETURN-REPORT.md 的字段完善提纲，不能把自动导出的文字当成实际实验结论。

## 状态组成

`.experience-strategy/state.json` 包含 schema_version、harness_version、revision、project、以 ID 为键的 goals / concerns / evidence / decisions、追加的 checkpoints，以及幂等请求记录。初始化产生 `goal-primary`。

| 对象 | 关键内容 |
| --- | --- |
| project | id、root、goal、scope、mode、version |
| goal | id、statement、journey、active |
| concern | 稳定 ID、类型、目标关联、观察/假设、策略与备选、验证、状态及下一触发条件 |
| evidence | 不可变 ID、材料类别、来源、摘要、适用版本 |
| decision | 不可变 ID、选择、理由、相关问题、Agent/用户来源及版本 |
| checkpoint | 节点、变化、检查深度与理由、摘要、下一步、限制和状态修改 |

所有 ID 都在项目内稳定使用。旧证据和旧决定不改写；更正时新增 ID，并在说明中指出替代关系。concern/goal 更新有历史记录，省略旧 ID 不会删除它。

## checkpoint 信封

必填字段：

| 字段 | 值 |
| --- | --- |
| request_id | 本次持久化请求的唯一 ID；相同内容的重试保持不变 |
| expected_revision | 最近一次 context 返回的 revision |
| node | intake / before-change / after-change / feedback / resume / handoff |
| project_version | 本次分析针对的具体版本或有意义的快照标签 |
| change | 本次输入或变化；不要伪造产品修改 |
| depth | none / focused / full |
| reason | 为什么采用这个检查深度 |
| summary | 实际得出的判断，允许维持原策略 |
| next_action | 一项具体下一步，或明确等待什么 |
| limitations | 未观察、未验证、无法测量的部分，字符串数组 |

可选数组 `goals` / `concerns` / `evidence` / `decisions` 按 ID 写入或更新，默认空数组。可选 `project_update` 只更新 goal / scope / mode，目标改变应附带可追溯 decision。脚本检查结构，判断是否符合用户真实意思仍是宿主责任。

最小无实质变化记录：

```json
{
  "request_id": "round-02-no-impact",
  "expected_revision": 1,
  "node": "before-change",
  "project_version": "baseline-01",
  "change": "准备修正文档拼写，产品界面和行为未改变",
  "depth": "none",
  "reason": "变化没有触及当前体验目标或旅程",
  "summary": "沿用现有策略，保留待验证问题",
  "next_action": "完成原任务；相关界面变化或反馈到来时复查",
  "limitations": ["没有重新操作产品；本次仅判断变更影响"]
}
```

上例是说明用的虚构输入。真实运行应填写实际变化和当前 revision。

## 一条问题记录

下面完整示例使用了**虚构的测试场景**，不得写成 原项目或任何真实产品的已发现缺陷：

```json
{
  "request_id": "fixture-intake-01",
  "expected_revision": 0,
  "node": "intake",
  "project_version": "fixture-v1",
  "change": "读取测试提供的阅读器需求说明",
  "depth": "focused",
  "reason": "本轮只分析中断后继续阅读的路径",
  "summary": "记录一个待复现的恢复问题，先比较修改现有路径与增加新窗口",
  "next_action": "操作一次关闭再打开的路径，记录实际恢复位置",
  "limitations": ["只有需求文档，尚未运行产品或访谈用户"],
  "goals": [
    {"id":"goal-primary","statement":"用户能在中断后继续原任务","journey":"阅读 → 关闭 → 再打开 → 继续","active":true}
  ],
  "evidence": [
    {"id":"e-doc-01","kind":"document","source":"fixture/brief.md#resume","summary":"测试文档声称关闭会丢失阅读位置；仅为文档主张","version":"fixture-v1"}
  ],
  "concerns": [
    {
      "id":"c-resume",
      "kind":"issue",
      "goal_ids":["goal-primary"],
      "statement":"关闭再打开是否会丢失阅读位置需要确认",
      "basis":"reported",
      "status":"open",
      "evidence_ids":["e-doc-01"],
      "strategy":"先复现，再判断是否需要恢复机制",
      "alternatives":["沿用现有路径，补充清晰返回入口","持久保存文章位置","使用独立阅读窗口"],
      "tradeoff":"更持久的上下文也可能恢复用户不想继续的旧任务",
      "next_trigger":"获得运行界面，或用户补充实际中断行为",
      "validation":{"status":"unverified","evidence_ids":[],"version":"fixture-v1","note":"未执行"}
    }
  ],
  "decisions": [
    {"id":"d-01","concern_ids":["c-resume"],"choice":"本轮先验证问题，不扩大为完整工作台","reason":"现有证据尚不足以选择较大重构","origin":"agent","source":"本轮分析建议，尚无用户选择记录","version":"fixture-v1"}
  ]
}
```

字段约定：

- `kind`（concern）：issue / opportunity。
- `basis`：observed（直接观察）/ reported（材料或用户报告）/ hypothesis（推断）。
- `status`：open / in-progress / awaiting-validation / resolved / deferred / dismissed。
- `evidence.kind`：document / observation / user-report / runtime-test / simulation。
- `validation.status`：unverified / pass / fail。
- `decision.origin`：agent / user；user 必须写实际来源，不能凭空代填。

策略变化时更新 concern 的 strategy / alternatives / tradeoff，并追加 decision；不要把旧选择从历史中抹去。

## 验证与重开

记录实际修改后，使用 `awaiting-validation`；保留尚未完成的检查。在指定版本上获得 pass 证据，才能使用 `resolved`，并写 `resolution_reason` 说明关闭范围。通过证据至少包含 observation / runtime-test / user-report 中一种。文档或 simulation 单独不能关闭真实问题。证据类型正确也不等于内容真实，宿主需检查其实际出处。

`resolved` 表示在记录的范围内得到支持，不表示长期产品价值或人类正式验收。验证版本必须等于当前 checkpoint 的 project_version。旧的 resolved 问题不会因任意版本号改变自动重开；宿主先检查旅程、状态或前提是否受影响。

复发时使用原 concern ID，改回适当状态，并在 `resolution_reason` 写明新证据和重开理由。没有新证据时不要丢弃原验证记录；新增证据与新的验证描述可以追溯旧判断。deferred / dismissed 同样需要 resolution_reason，并保留 next_trigger；它们不计入已验证成功。

## 冲突、错误与离线交接

- 相同 request_id + 相同完整输入：重试返回原回执；不同输入使用同 ID 应被拒绝。
- revision 过期：先重新 context、比较更新，再生成新请求。不要只替换 expected_revision。
- 写入失败：先查询原请求/最新记录，不盲目重复工作。保留输入文件方便对账。
- `.experience-strategy` 或数据文件是 symlink：脚本拒绝访问，使用实际拥有的项目目录。
- 锁遗留：确认没有写入者，备份状态并检查锁的实际状态后再人工恢复；不要以自动删除锁绕过冲突。
- 导出目标必须是新目录，不覆盖已有回传材料。

跨机器恢复时，将导出的 state.json 放到目标项目的 `.experience-strategy/state.json`（目标位置必须尚无状态；已有状态先核对，不能覆盖）。直接运行 context 和 validate，不用 init 重建历史。若 context 返回 `project_root_moved:true`，说明 state 记录的原目录与本机不同；后续命令使用本机实际 `--root`，核对项目身份、版本和证据引用，不把旧绝对路径当作可访问材料。checkpoints.jsonl 是方便阅读的导出；完整可恢复历史已包含在 state.json 中。

无 Python 的 Agent 使用包内 EXPERIENCE-HARNESS.md 的 portable 状态格式，存到 `.experience-strategy-portable/` 或会话中，不要手工拼装本脚本的 state.json。报告中明确该方式没有脚本结构检查、原子写入或冲突保护，两种格式不可直接互换。完全无文件能力时使用下面的完整接力格式：

```text
体验状态接力 · harness 0.1.0 · transcript-only
项目/目标/范围/当前版本：
本轮节点/最近检查材料/观察盲区：
体验目标（稳定 ID、旅程）：
问题与机会（稳定 ID、目标、依据、状态、策略、备选、验证、下次触发）：
证据索引（ID、类别、来源、版本、摘要）：
决定（ID、选择、理由、来源；保留否决项）：
本轮完成/未完成：
下一实际行动：
下个 Agent：先读本块和 SKILL.md，执行 resume；不要宣称后台在线。
```
