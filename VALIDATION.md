# 体验策略 Harness 验证记录

## v0.3.0-alpha.3 只读状态工作台

2026-11-17，macOS。106 项自动测试通过，其中核心和状态工作台 75 项、Codex 适配器 22 项、DeepSeek Harness 原生框架 9 项。另在 Chromium 147 实测页面及文件快照，独立 DSH 安装包经官方 Loader 和快照导出检查。

| 场景 | 实际观察 |
|---|---|
| 项目与案件 | 同一界面能查看候选就绪、等待行为证据，以及已有体验关注但没有角色案件的项目。用户效果单独展示。 |
| 跨进程交接 | 浏览器保持打开，另一个进程提交 Critic 交付后，页面轮询显示 Execution 接手。 |
| 刷新与恢复 | 例行读取仅查询已记录状态，手动刷新核对文件。已展开的交付保持展开，模拟断线保留上次数据，恢复连接可重读。 |
| 离线查看 | 直接打开导出的 HTML，在桌面和 375px 窄屏切换项目，没有对外部网络发起请求。 |
| 只读保证 | 检查空项目、已提交案件、状态不可读、文件变化、多项目及重试。轮询不会确认待检或提交角色结果。 |

这些结果覆盖本机界面与数据流。工作台记录的角色阶段来自最后一次持久化交付。实际模型是否正在运行、首次使用者能否自行理解界面，以及设计成效，仍需要各自的证据。[启动与导出](README.md#打开状态工作台)

## v0.3.0-alpha.2 创作分工

2026-11-17。在 macOS 完成 96 项自动测试。核心 65 项，Codex 适配器 22 项，DeepSeek Harness 原生框架 9 项。其中 DeepSeek 通过真实工具登记和执行使用确定性模型替身。Codex 测试使用符合宿主协议的事件和真实 Python 子进程。[工程记录](validation/creation-tests.json)

- 默认演示交付可打开的 HTML 候选，并实际检查文档结构。独立产物检查直接交给 Verifier；显式用户验证演示仍使用标记为 fixture 的模拟分支。
- 返工须保存新候选；工单、空文件、失效候选或被调换的检查记录均在相应交接处被拒绝。已有案件可按上一版协议续接。
- 在一个隔离的阅读列表项目中，根据实际组件、样式和截图制作互动候选，在 Chromium 的 480 和 320 像素视口，以及 360 像素触控模拟中核对默认态、收藏与撤回、焦点、筛选与元数据布局。提交后回读得到 candidate_ready、User Evidence 关闭、用户效果未验证。没有真人参与，产品采用与真实设备效果仍待外部评估。
- 独立 DSH tarball 经官方 Loader 加载，在宿主循环中发现了当前创作角色，并保留普通待检。通用演示与真实产品样稿分别记录。

三种阶段复验命令见[阶段与交付指南](references/role-engine.md)。下方旧版段落仅描述对应标签及当时的结果。

## v0.3.0-alpha.1 角色原型

2026-11-17，macOS。87 项自动测试通过。另从发布用的 DSH tarball 加载官方 AgentLoop，并在解包目录执行完整演示。[可复核的工程记录](validation/role-engine-tests.json)

| 层 | 实际执行 | 结果 |
|---|---|---|
| Kernel、Controller 与原有核心 | 58 项 Python 测试，包含角色权限、反证、等待恢复、并发重试、证据变更和跨项目绑定 | 58 项通过 |
| Codex Adapter | 21 项测试，以事件输入驱动真实 Python 子进程和状态库；覆盖当前角色的发现、阶段改变后的上下文更新和故障处理 | 21 项通过 |
| DeepSeek Harness Adapter | 官方 0.2.2-rc.3 框架的原生循环，使用确定性模型替身。含读取角色卡、提交与恢复下一角色 | 8 项通过 |
| 独立 DSH 安装包 | 让官方 Loader 读取 tarball 中的 patch 并运行原生循环 | 发现当前角色，普通待检保留，模型替身共运行两步 |
| 从解包目录启动演示 | 三个案例共用一个行为主张，第四个案例实际检查 HTML 标记 | 模拟支持证据维持提案，模拟反证修订提案，静态证据导致暂缓，恢复后可改判；产物断言仅调用 Verifier |

在一次隔离的真实阅读列表案例中，一个新开的 Codex Agent 读取实际截图、样式和组件代码，随后按四张角色卡依次提交。截图支持对控件呈现的观察；首次使用者能否自行找到入口仍缺少任务记录。Judge 的结果是等待证据；四次交付后停止。这是一次单宿主试用，外部读者无法依据公开包独立复核私有产品材料。跨宿主复评、真人任务、独立设计师判读，以及这种流程对体验质量和投入成本的影响仍待实测。

复验核心与宿主测试使用下方命令。复验原型的角色分支可在仓库根目录执行以下命令，指定尚不存在的输出目录。

```sh
python3 scripts/engine_demo.py --output /tmp/experience-role-validation-01
```

演示的 RESULTS.md 汇总结局，TRACE.json 给出各角色提交与阶段变化。[角色设置及实际接入](references/role-engine.md) · [外测回传模板](templates/RETURN-REPORT.md)

## 历史记录 · MVP 0.2.0 执行层验证

日期：2026-11-16。以下是工程验证，未证明设计质量、用户任务表现或真人接受度提升。

## 实际完成

| 层 | 环境与范围 | 结果 |
|---|---|---|
| v0.1 持久状态兼容 | macOS / Python 3.9.6，原状态工具不改协议 | 16 项通过 |
| v0.2 共享执行层 | Python 3.9.6 / SQLite / 临时项目 | 21 项通过 |
| Codex 适配器 | 原生形状的 stdin 事件，实际 Python 子进程与状态落盘 | 19 项通过，其中 2 项贯通完整执行层 |
| Codex 原生配置发现 | codex-cli 0.162.0-alpha.2 / app-server `hooks/list` | 7 个事件被识别，无解析错误，全部仍为 untrusted |
| DSH 原生 Agent 循环 | 官方 0.2.2-rc.3 框架 + 确定性模型替身 / Node 24.22.1 | 7 项通过 |

共 **63 项自动测试**，另有 Codex 原生配置发现和独立 DSH 安装包检查。完整测试源随仓库提供，计数见 [工程记录](validation/runtime-tests.json)。

独立 DSH tarball 已离线安装，再由官方 Cordis Loader 读取其 bundle patch 并运行原生 AgentLoop；实际走了两次确定性模型步骤，未完成的检查保留。记录见 [安装包烟测](validation/deepseek-package-smoke.json)。

Codex 配置发现使用本次进程的 inline hooks 覆写，不修改全局配置或 hooks 信任，不发起模型 turn。记录见 [codex-discovery.json](validation/codex-discovery.json)。这证明实际安装版本能识别这些事件与 handler 配置；没有证明用户项目的 hooks 已经加载、被信任或完成真实模型补检。

DSH 测试加载官方 Cordis、Session、工具执行器、AgentRegistry 和 AgentLoop。确定性 provider 用来强制产生可重复的“忽略检查 / 调工具 / 完成”序列，工作目录服务使用固定目录测试替身。实际验证了原生 Stop → steer → 下一模型步骤 → checkpoint 工具提交。没有调用线上 DeepSeek 模型，没有使用 API key。

## 关键异常与修正

- 缺少检查时确实触发补检；反复忽略时有界结束，保留 pending。
- 文件在分析期间或提交过程中改变时拒绝确认；旧回执不能清除新变化。
- 并发事件去重；策略提交后、执行确认前中断可以按相同请求恢复。
- 新会话保留待检，不以宿主退出替代验证。
- 稳定 `context_key` 避免无变化的工具事件反复注入完整上下文。
- 中断 / 结束不扫描文件或重放策略历史，数据库等待最多 0.2 秒；DSH 中断记录另有 1 秒子进程截止。测试包括故意阻塞的记录器，取消不触发重新续跑。
- 未 setup 的项目不激活；安装器保留其他 hooks，拒绝符号链接等不安全路径。
- 检查失败对宿主可见，适配器不把异常当作通过。

## 可复验命令

仓库根目录：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s adapters/codex -p 'test_*.py' -v
python3 scripts/verify_codex_discovery.py --codex /path/to/codex
```

DSH 测试（首次安装依赖需要网络；测试本身不调用外部服务）：

```sh
cd adapters/deepseek
npm ci --ignore-scripts
npm test
```

构建独立 DSH 包时从仓库根目录运行：

```sh
node adapters/deepseek/build.mjs
npm pack --ignore-scripts ./adapters/deepseek --pack-destination /path/to/output
```

## 尚未验证

- 用户在 Codex 审核 hooks 后，用真实模型完成多轮体验评审。
- 用户自己的 DSH profile、真实模型及真实项目连续运行。
- Windows、其他 DSH 版本、长时间大项目状态增长和宿主升级兼容性。
- 真实用户效果、相比普通 Agent 的因果增益、token / 时间 / 费用净收益。

一次续跑仍可能被模型忽略。有限预算到达后保留待检并允许结束；这不是永不放行的发布门禁。模型可以提交结构有效但内容薄弱的判断，因此外测必须检查实际产物和证据，不能只统计 checkpoint 数量。

旧 `harness.py` 在进程恰好被硬杀于提交期间时仍可能遗留原有 `write.lock`。必须先确认没有活动写入者再按工具提示恢复；本版不擅自删除锁。SQLite 执行状态自身使用事务恢复。

此前单文件受控演练保留在 [v0.1.0 验证记录](validation/v0.1.0.md)，其人工记录、模拟情境和同宿主限制继续适用。外测按 [实验指南](references/experiment.md) 与 [回传报告](templates/RETURN-REPORT.md) 进行。
