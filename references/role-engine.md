# 体验引擎的角色与流程

先确定这轮要交付什么。制作设计候选、检查已有产物、验证用户行为，各自有可完成的条件。一个问题可以同时处于“候选已做好”和“用户效果待验证”。

| 当前任务 | 开案字段 task_stage | 谁接手 | 完成条件 |
|---|---|---|---|
| 做一版可检查的设计 | `create` | Design Critic → Execution → Measurement | 有候选文件、检查记录和已知限制。检查发现问题可以返回 Execution 再做一版。 |
| 检查某项已有界面事实 | `artifact_check` | Verifier | 在指定版本和范围内记录事实；如声称可键盘操作，应实际使用键盘检查。 |
| 回答一个关于人如何使用产品的问题 | `user_validation` | Strategist → Critic → User Evidence → Design Judge | 对照原假设检查实际用户证据，记录维持、修订、撤回、暂缓或交负责人的理由。 |

创作期间 User Evidence 关闭。Measurement 可检查渲染、状态反馈和输入行为，“读者能否自行发现入口”单独保留。人数、研究方法、成效指标随验证问题确定。系统不预设招募任务。为兼容上一版，省略 `task_stage` 的底层调用延续原有产物或权衡路由；新宿主应显式传入阶段。创作演示默认使用 `create`。

## 在自己的项目使用

先按 [项目初始化指南](../README.md) 建立体验目标和 runtime，把 watch 限定为不可变的本轮基线，例如 `baseline/**` 或相关源码。至少一个文件应当匹配。把候选和检查记录置于 watch 之外。同一案例持续绑定原始基线，产品源码发生变化则用新 case 复核。

保存为 open.json，并指定项目根。请写出本轮想改变或检查的具体对象。

```json
{"case_id":"reading-save","task_stage":"create","goal":"在列表中保留想稍后阅读的文章","claim":"把行内收藏入口在默认态显现，同时保留文章来源和日期","claim_type":"artifact","mode":"live"}
```

```sh
python3 scripts/engine.py open --root /path/to/project --input open.json
python3 scripts/engine.py context --root /path/to/project --case-id reading-save
python3 scripts/engine.py submit --root /path/to/project --input submit.json
```

读取返回的 `brief`、`next_role`、`candidate_dir` 和历史。每次提交带上刚读取的 `case_id`、`binding`、`expected_revision`，为这次请求指定 `request_id`，以及 `role`、`output`。重试同一次提交时沿用同一请求和内容。

1. **Design Critic** 交付具体改动（`change`）、代价（`tradeoff`）和可观察的验收条件（`acceptance`）。例如把收藏星标常显，代价是增加列表视觉密度，验收时同时看入口与元数据。
2. **Execution** 用宿主已经获准的能力制作可检查的候选，把文件写入返回的专属 `candidate_dir`，提交 `change`、项目相对 `candidate_refs` 与 `review_steps`。只发工单无法完成此步。若宿主只能分析，就如实保留待制作状态。
3. **Measurement** 对提交的候选逐项检查。提交 `checks`（每项含 `check`、`result: pass|fail`、`observation`）、项目相对 `evidence_refs`、`limitations`，以及 `outcome: ready|rework`。把检查记录置于项目内，例如 `checks/interaction.json`。返工时另存新候选，留住被退回的版本。
4. `candidate_ready` 表示该交付在记录的检查范围内已就绪。创作案件始终保留 `user_evidence=disabled` 和 `user_outcome=unverified`。决定是否采用，以及是否开展用户研究，由项目负责人按任务单独处理。

产物检查使用 `claim_type=artifact`。用户验证使用 `claim_type=behavior`；线上案例只有与问题匹配的实际用户任务材料才能支持或反驳行为主张。缺材料时可暂缓，取得新材料后显式 `resume`。模拟分支只能在 fixture 中演练，核验文件存在及内容指纹不能独立鉴定参与者身份。

## 系统怎样持续运作

| 层 | 职责 |
|---|---|
| Adapter | Codex hooks、DeepSeek Harness 工具或 CLI 从项目状态读回阶段与下一角色。宿主退出后，下次工作继续。 |
| Kernel | 持久保存项目、基线、交付、证据文件指纹及提交回执，拒绝错角色、过期提交和被调换的候选。可用 concern_id 关联本项目原策略记录。 |
| Controller | 按当前任务选择接手人，根据已记录的检查结果结束、返工或等待新证据。 |
| Capabilities | 宿主实际设计、实现、打开预览和检查交互，或分析已经获得的研究材料。同一宿主可以分步承担角色。 |

角色提交只推进当前案件。runtime checkpoint 单独确认当前的产品文件变化已被检查。若产品基线改变，用新 ID 开案并以 `supersedes` 引用旧案；新案重新绑定材料。项目的采纳决定、用户表现和真实发布保持单独记录。CLI 使用 Python 3.9+ 及 POSIX 文件访问。

## 在独立项目演练

从完整源码目录执行。每个输出目录须尚不存在。演示使用通用阅读卡样本，可直接查看输出的 RESULTS.md、角色 TRACE.json 和引用的实际文件。

```sh
python3 scripts/engine_demo.py --output /tmp/reading-create-01
python3 scripts/engine_demo.py --stage artifact_check --output /tmp/reading-inspect-01
python3 scripts/engine_demo.py --stage user_validation --output /tmp/reading-validation-01
```

默认演示写出一个可操作 HTML，让保存控件从折叠菜单移到正文，并实际解析候选的文档结构。第三条命令使用模拟材料测试不同裁决和跨进程恢复。真实任务用 `engine.py open` 进入项目，切换宿主时用 `context` 查看当前阶段和既有交付。
