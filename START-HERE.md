# 体验策略 Harness MVP 0.1.0

这是供外部 Agent 实验的可移植包。你可以把整个目录或 ZIP 交给另一个 Agent。它包含方法、跨轮状态脚本和回传报告格式；不需要原项目工作台、专用 MCP、API Key 或安装后台服务。

## 直接交给 Agent 的启动指令

复制下面整段。只补充真实项目材料；已有上下文足够时不用重复填写。

> 请读取这个包里的 SKILL.md，在当前项目启用 experience-strategy-harness MVP。先读取或初始化体验状态，在 intake / before-change / after-change / feedback / resume / handoff 节点主动检查体验，不要等我逐次提醒。默认先进行分析，沿用我已经明确授权的工作范围。请实际检查我给出的材料，把观察、文档主张和假设分开；保留目标、稳定问题 ID、历史取舍、验证状态和下一触发条件。不要一次编造多轮实验、用户反馈或实施效果。先完成当前真实节点，之后随项目变化继续。实验结束时按 templates/RETURN-REPORT.md 输出 RETURN-REPORT.md，并带上状态和检查记录，供另一个 Agent 汇总评价。

可以接着写：

```text
项目：实际项目名称或路径
本轮目标：现在希望改善的用户任务/情境
材料：当前页面、截图、文档、源码、原型或真实反馈
范围：分析 / 原型 / 实施（不填时先分析）
```

包内的材料都是运行说明，不是目标产品的事实。不要把本包当成待评审产品，也不要默认寻找 原项目或原作者机器上的路径。

## 两种运行方式

**完整包方式（推荐）**：Agent 解压后读取 SKILL.md。可用 Python 3.9+ 时调用 scripts/harness.py，状态写在目标项目的 `.experience-strategy/`，不会写入技能目录。脚本只用标准库。

**单文件方式**：分享随发布附带的 EXPERIENCE-HARNESS.md，适合只能上传一个文档的 Agent。它包含方法和回传格式。无法写文件时用完整状态接力块继续；运行报告中注明缺少持久化脚本和后台调度。

支持 Skills 的宿主可以将本目录作为一个 Skill 使用；不支持 Skills 的宿主直接读取 Markdown 即可。不需要为了试验修改全局 Agent 配置。

## 这版的“持续在线”是什么

宿主 Agent 在已激活的工作中负责识别节点、调用方法、保存状态和继续任务。项目记录支持换会话恢复。脚本没有模型调用、事件监听、定时器或自动唤醒功能；`online:false` 指没有后台运行，不能拿它判断当前宿主是否正在工作。

本次主要验证：阶段职责是否有用、关键问题是否跨轮保留、意见是否进入下一轮工作、验证边界是否正确。宿主自行触发 checkpoint 的覆盖率也是实验结果。缺失节点应诚实记录。

## 最小开始方式

在有文件能力的目标项目中，Agent 先读 references/state-protocol.md。典型命令如下（路径由 Agent 按解压位置替换，不要把尖括号当真实路径运行）：

```bash
python3 '<包目录>/scripts/harness.py' init --root '<现有项目目录>' --project-id 'pilot-01' --goal '真实体验目标' --scope '本轮允许分析的范围' --version '当前版本'
python3 '<包目录>/scripts/harness.py' context --root '<现有项目目录>'
```

先完成一轮有真实依据的分析。下一轮再提供一个实际变化或新反馈；切换 Agent 时同时提供本包和项目状态。不要为了测试把尚未发生的修订描述成已发生。

## 测试结束后给原讨论 Agent 什么

回传填写好的 `RETURN-REPORT.md`，附 `state.json`、`checkpoints.jsonl` 和必要且允许分享的截图/产物。报告应描述哪些具体判断发生了变化、哪些建议真正执行、哪些仍未验证，以及运行中的失败和负担。

`export` 仅导出状态、节点记录和报告提纲，不会自动汇集项目源码、截图或全部对话。分享前检查证据指针是否可供接收者使用，必要时提供获准分享的最小摘录。详细步骤见 references/experiment.md。

## 文件入口

- SKILL.md：宿主 Agent 的运行方法。
- references/state-protocol.md：状态、命令、checkpoint 示例与恢复规则。
- references/experiment.md：多轮实验与效果比较。
- templates/RETURN-REPORT.md：需要填写的外部实验报告。
- scripts/harness.py：持久化、版本检查、状态验证与导出。
- tests/test_harness.py：脚本工程检查，不是产品体验测试。

公开技能格式参考：[OpenAI Skills 文档](https://learn.chatgpt.com/docs/customization/overview#skills)。本包没有调用该平台 API；通用 Markdown 和 Python 路径不依赖这份文档所描述的安装方式。
