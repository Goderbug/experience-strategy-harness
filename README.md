# Experience Strategy Harness

让设计 Agent 在工作过程中持续保留体验目标、历史取舍与验证状态，并在实际改动后进行检查。

**0.3.0-alpha.2 支持创作、产物检查和用户验证。** 做设计时，Critic 明确取舍，Execution 制作可检查的候选，Measurement 检查实际产物。用户效果单独保留为待验证。

从本版源码根目录运行 `python3 scripts/engine_demo.py --output /tmp/reading-create-01`（新目录）。打开输出的 `RESULTS.md` 查看原版、可操作候选与检查记录。[在实际项目分阶段接入](references/role-engine.md)

## 开始

```sh
git clone --branch v0.3.0-alpha.2 https://github.com/Goderbug/experience-strategy-harness.git
cd experience-strategy-harness
```

选择实际使用的宿主：

- **Codex**：[安装与信任 hooks](adapters/codex/README.md)。提供原生插件清单和项目级 hooks 安装器。
- **DeepSeek Harness / dsh**：[安装原生插件](adapters/deepseek/README.md)。接入原生 Agent 循环，复用宿主模型和工具，不另建 DeepSeek API 调用器。
- **其他 Agent / 只上传文档**：[START-HERE.md](START-HERE.md) 与 [EXPERIENCE-HARNESS.md](EXPERIENCE-HARNESS.md)。这是手动触发的可移植降级模式。

角色原型见 [v0.3.0-alpha.2 Release](https://github.com/Goderbug/experience-strategy-harness/releases/tag/v0.3.0-alpha.2)，上一版执行层见 [v0.2.0 Release](https://github.com/Goderbug/experience-strategy-harness/releases/tag/v0.2.0)。Python 核心只依赖标准库，要求 Python 3.9+；DSH 插件的宿主版本要求见适配器文档。

## 执行层如何工作

```mermaid
flowchart LR
  A[宿主会话与工具事件] --> B[恢复目标与取舍]
  B --> C[检测观察范围内的文件版本]
  C --> D[持久记录待检事项]
  D --> E[将检查任务注入当前 Agent]
  E --> F[Agent 观察并提交体验判断]
  F --> G[核验版本与提交回执]
  G --> H[清除对应待检事件]
  D --> I[结束前有限补检]
  I --> E
```

| 环节 | 本版行为 |
|---|---|
| 会话开始 / 恢复 | 读回目标、未决问题和最近取舍；保留上次遗漏 |
| 本轮任务开始 | 注入体验关注，登记本轮影响判断 |
| 工具执行前 | 带入当前约束；这是提示，不是写入前强制审批 |
| 工具执行后 / 结束前 | 对配置范围做内容快照，识别新增、修改、删除 |
| 结束前仍有待检 | 默认最多续跑一次；不会无限自我审查 |
| 判断提交 | 检查对应事件、内容快照和状态版本后确认，旧回执不能清掉新变化 |
| 中断 / 失败 | 保留待检；下次恢复，不将中断写成通过 |

适配器负责**何时介入及是否留下记录**，宿主 Agent 负责**观察、分析、策略与验证**。验证器能检查结构和版本，不能证明判断质量或证据真实性。通过 `depth: none` 可以有理由地跳过无关变化，避免每次改动都生成建议。

## 启用一个项目

先在现有目标项目建立体验目标，再明确文件观察范围：

```sh
python3 scripts/harness.py init --root /path/to/project \
  --project-id pilot-01 --goal '让用户可靠完成核心任务' \
  --scope '当前授权的旅程与页面' --version baseline --mode analysis-only
python3 scripts/runtime.py setup --root /path/to/project \
  --watch 'src/**' --watch 'public/**' --max-continuations 1
python3 scripts/runtime.py context --root /path/to/project
```

将路径、目标和 watch 范围换成真实项目，再按对应宿主文档安装。运行时仅在明确 setup 的项目生效；安装插件本身不会对所有项目开启检查。真实反馈仍需要提供给 Agent；只读取文件快照无法知道用户遇到的全部体验问题。

## 状态与边界

- `.experience-strategy/state.json`：目标、问题、证据、取舍与检查历史。保留 v0.1 状态协议兼容性。
- `.experience-strategy/runtime.sqlite3`：执行状态、待检事件、续跑预算和确认回执。
- `scripts/runtime.py context`：查看执行状态与可提交的 checkpoint 模板。
- `.experience-strategy/engine.sqlite3`：显式开启 role case 时创建的案件、角色交付和回执。
- [运行协议](references/runtime-protocol.md)：触发、确认、恢复与观察范围。
- [分析状态协议](references/state-protocol.md)：证据类型、问题状态与持久化规则。

这里的“持续”是**宿主运行期间的事件驱动介入，加上跨会话恢复**。宿主退出后没有后台轮询，也不会自动启动 Codex 或 dsh。分析状态中的 `online:false` 保留其原义：未配置独立后台观察器，不能用它判断 hooks 是否安装成功。

## 验证和外测

[VALIDATION.md](VALIDATION.md) 分开记录核心合约、适配器测试、真实宿主接入测试和未完成的真实模型实验。工程测试通过不等于体验效果提升。

请按 [实验指南](references/experiment.md) 跑一个真实项目，回传 [RETURN-REPORT.md](templates/RETURN-REPORT.md)。重点比较：漏检是否减少、旧决定是否被保留、策略是否改变实际产物、增加了多少负担。独立事件清单仍然必要，不能用 harness 自己生成的记录充当完整覆盖分母。
