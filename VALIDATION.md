# MVP 0.2.0 执行层验证

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
