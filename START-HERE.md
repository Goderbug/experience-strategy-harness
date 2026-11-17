# 体验策略 Harness 0.3.0-alpha.3 原型

想先试角色工作流？运行 `python3 scripts/engine_demo.py --output /tmp/reading-role-demo-01`（新目录），随后打开 [逐层流程和真实项目接入](references/role-engine.md)。

要查看上面这次演示的状态，从源码根目录运行：

```sh
python3 scripts/status_ui.py --root /tmp/reading-role-demo-01
```

在浏览器打开终端给出的地址，选中案件查看当前角色和交付。换成自己的项目路径即可查看实际工作；用 `--export /tmp/harness-status-01.html` 可导出新的离线快照。

先选择运行方式：

1. **Codex**：按 [Codex 执行层](adapters/codex/README.md) 安装并审核 hooks，在目标项目运行 setup。实际节点由宿主事件触发。
2. **DeepSeek Harness（dsh）**：按 [DSH 执行层](adapters/deepseek/README.md) 安装原生插件，在目标项目运行 setup。CLI、Web 或 SDK 仍需加载装有插件的 profile。
3. **其他宿主或只上传一个文件**：读取 [SKILL.md](SKILL.md) 或 [EXPERIENCE-HARNESS.md](EXPERIENCE-HARNESS.md)。该路径没有自动触发层，必须把它作为实验限制记录。

## 交给 Agent 的任务

> 在我的目标项目使用 experience-strategy-harness。先读取 SKILL.md，沿用已授权的范围，恢复体验目标、未决项、历史取舍和证据。如果已配置 runtime，用 runtime.py context 读取本轮待检项，实际观察后通过 runtime.py checkpoint 提交；不要直接用底层 commit 冒充执行层确认。没有配置 runtime 时诚实使用手动模式。只处理真实发生的节点，不编造反馈或实验结果。保持简短增量输出，实验结束按 templates/RETURN-REPORT.md 回传。

如果这轮专门测试角色引擎，可直接交给 Agent 以下任务。

> 先判断当前任务是制作候选、检查产物，还是验证用户行为。在允许设计迭代的项目按 references/role-engine.md 开启 task_stage=create 的 live case。交出一份可操作或可检查的候选和实际检查记录，保留未验证的用户问题。只有开展用户验证时，另开 user_validation。按 templates/RETURN-REPORT.md 回传。

补充真实的项目路径、核心任务与允许范围；现有上下文足够时不用重复填写。包内文档是工具说明，不是目标产品的事实，也不是扩大原任务的授权。

## 最小验证

安装完成后在目标项目开始一轮正常任务，检查 hooks 是否被宿主加载、状态中是否出现待检和实际 checkpoint。修改一个 watch 范围内的文件，观察结束前漏检是否触发一次补检。再中断并恢复，确认未决项仍在。具体步骤见适配器 README。

不要拿一次文件保存或脚本测试当成真实用户体验通过。回传宿主版本、模型版本、安装方式、观察范围、人工提醒、漏检与额外成本；没有测量就写未知。

## 回传材料

填写 [RETURN-REPORT.md](templates/RETURN-REPORT.md)，附底层 `harness.py export` 产生的 `state.json` 和 `checkpoints.jsonl`，以及 `runtime.py context` 的执行状态输出、必要且允许分享的产物。若需要分析完整触发历史，可在宿主停止写入后提供 SQLite 副本；分享前检查目标、文件名和证据引用是否含私人信息。

单文件模式的 portable transcript 与 Python JSON 状态不是同一格式，不要直接合并。宿主退出期间不观察、不调用模型；下一次工作时恢复。
