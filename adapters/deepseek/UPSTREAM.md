# DeepSeek Harness 接口基线

核对日期：2026-11-16。官方仓库 `deepseek-ai/deepseek-harness`，提交 **39163dd30f703a79079e2d2446545cff3c453738**，提交时间 2026-11-13，发布版本 **0.2.2-rc.3**。插件与测试使用该版本公开接口。

| 接入点 | 官方固定版本依据 |
| --- | --- |
| Bundle manifest、`dsh plugin` 安装与 profile 配置 | [Package and install a plugin](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/develop/basic/publish.md) |
| `agent/created`、`agent/pre-step`、`agent/turn-stopping`、`inject` / `steer` | [runtime-types.ts](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent/src/runtime-types.ts) |
| 官方 Stop hook 通过 `agent.steer` 续跑的例子 | [hooks-claude-code/index.ts](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/experimental/hooks-claude-code/src/index.ts) |
| `tools/result` 为同步的最终结果通知 | [tools/events.ts](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/events.ts) |
| 工具必须提供 canonical JSON 输出及 `output.schema` / `render` | [tools/contracts.ts](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/tools/src/contracts.ts) |
| 会话工作目录 `ctx.workingDirectory.get(session)` | [working-directory/index.ts](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/session/working-directory/src/index.ts) |
| 原生 hook 的真实 AgentLoop 测试组合 | [interception.spec.ts](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/core/agent-loop/tests/interception.spec.ts) |

执行层使用官方服务和事件，不修改其模型循环，也不把请求转发到另一个“DeepSeek API Agent”。上下文来源标记为 `experience-strategy-harness`，不会伪装为用户发言或用户授权。官方 Stop hook 例子要求插件自行限制强制续跑，本包同时用持久计数与进程内标记限制它。

重新支持其他 DSH 版本时，应重新检查上述接口、更新 `engines.dsh` 与精确测试依赖，并运行原生集成测试。网页说明或名字相同不代表二进制兼容。
