# Experience Strategy Harness

A portable, experimental harness for maintaining experience goals, design decisions, and validation across agent work sessions.

体验策略 Harness：让设计 Agent 在项目推进中持续保留体验目标、关注点、历史取舍和验证状态，并在不同工作节点承担不同职责。

当前版本：**MVP 0.1.0**。采用宿主 Agent 主动检查与持久记录；不包含后台监控、定时器或模型调用服务。

## 直接开始

- **只上传一个文件**：下载 [EXPERIENCE-HARNESS.md](https://github.com/Goderbug/experience-strategy-harness/releases/download/v0.1.0/EXPERIENCE-HARNESS.md)，连同实际项目材料交给 Agent。
- **使用完整包**：从 [v0.1.0 Release](https://github.com/Goderbug/experience-strategy-harness/releases/tag/v0.1.0) 下载 ZIP，解压后读取 [START-HERE.md](START-HERE.md) 和 [SKILL.md](SKILL.md)。
- **从源码使用**：克隆仓库，将整个目录交给支持文件工具的 Agent；Python 状态工具只依赖标准库，要求 Python 3.9+。

```sh
git clone https://github.com/Goderbug/experience-strategy-harness.git
```

将下面的指令和项目材料发给 Agent：

> 请读取这个包里的 SKILL.md，在当前项目启用 experience-strategy-harness。沿用我已明确授权的范围，在 intake、before-change、after-change、feedback、resume、handoff 节点主动检查体验，保留目标、稳定问题 ID、历史取舍、证据和验证状态。先处理当前真实材料，不要虚构多轮实验或用户反馈。实验结束时按 templates/RETURN-REPORT.md 输出报告，并保留状态和检查记录。

只有单文件时，将上面的 SKILL.md 换成 EXPERIENCE-HARNESS.md。支持 Skills 的宿主可使用本目录；其他宿主直接读取 Markdown 即可，无需专用插件或 API Key。

## 核心机制

| 节点 | 职责 |
|---|---|
| intake | 建立当前任务、目标、情境和初始关注 |
| before-change | 判断改动影响，将相关体验约束带入任务 |
| after-change | 查看实际产物、残留问题和验证缺口 |
| feedback | 更新假设与策略，保留采纳、拒绝和修改理由 |
| resume | 恢复目标、未决项与历史取舍，核对证据版本 |
| handoff | 交接状态、限制、下一行动及触发条件 |

每次按影响选择 none / focused / full；允许维持原状。实现完成和体验验证分别记录，已解决问题可以因新证据重开。

## 状态与恢复

Python 模式使用 `scripts/harness.py` 的 `init`、`context`、`commit`、`validate`、`export`，将状态保存到目标项目的 `.experience-strategy/`。具体参数和可执行示例见 [状态协议](references/state-protocol.md)。脚本提供版本冲突检查、幂等提交、状态校验和导出。

无 Python 时使用单文件入口中的 portable 格式；无文件工具时交接完整聊天状态。新会话仍须重新激活并带回状态。两种状态格式不可直接互换。

## 做一次真实实验

按 [实验指南](references/experiment.md) 选择一个实际用户旅程，随真实变化多轮推进。执行者单独记录事件清单，以发现漏触发和人工提醒，不能只根据 Agent 自己生成的日志判断覆盖率。

结束后填写 [RETURN-REPORT.md](templates/RETURN-REPORT.md)，带回状态、检查记录及必要产物。区分 Agent 行为、工程结果、真实用户观察和受控模拟；没有对照时不声称因果提升。

## 检查

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

16 项脚本合约测试已通过。公开包附 [验证记录](VALIDATION.md)，说明工程检查和同宿主受控演练的范围；这些不证明跨宿主持续运行或真实用户体验改善。
