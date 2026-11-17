# Codex 执行层

这层使用 Codex 原生生命周期 hooks，复用当前会话中的模型和工具。项目启用后，hooks 自动恢复体验状态、登记变化和待检项，并在结束前最多请求有限次补检。它不启动另一个模型进程，也不在 Codex 退出后运行。

协议依据：[Codex Hooks](https://learn.chatgpt.com/docs/hooks) 与 [官方插件打包说明](https://developers.openai.com/plugins/build/plugins)，核对日期 2026-11-16。需要支持这些 hooks 的 Codex 客户端；旧客户端应升级或使用手动模式，不能仅凭存在配置文件认定已启用。

当前命令打包面向 macOS / Linux 的 POSIX shell，要求 Python 3.9+。Windows 原生命令转义与生命周期尚未验证。

## 项目级安装

将这个仓库放在长期保留的位置。以下命令从仓库根目录运行；把 `/path/to/project`、目标和观察范围替换成实际项目。已经执行过 `init` 的项目继续使用原有状态，不需要重建。

```sh
python3 scripts/harness.py init --root /path/to/project \
  --project-id pilot-01 --goal '让用户可靠完成核心任务' \
  --scope '当前授权的旅程与页面' --version baseline --mode analysis-only
python3 scripts/runtime.py setup --root /path/to/project \
  --watch 'src/**' --watch 'public/**' --max-continuations 1
python3 adapters/codex/install.py --root /path/to/project
```

安装器只合并这个项目的 `.codex/hooks.json`，保留其他 hooks；重复安装不会重写等价配置。命令引用当前仓库和 Python 解释器的绝对路径。移动或删除仓库、替换解释器后，需要重新运行安装器。

**还需要在 Codex 中审核并信任项目与这些 hooks。** CLI 使用 `/hooks`；桌面端使用 **Review hooks** 或 **Settings > Hooks**。配置或脚本更新后可能需要重新审核。安装器不会替用户授予信任，也不使用跳过信任的启动参数。

在该项目新开或恢复一次 Codex 会话，确认 hooks 在宿主中显示为已加载、已启用且已信任，然后查看执行状态：

```sh
python3 scripts/runtime.py context --root /path/to/project
```

只安装 hooks 不会启用所有项目。适配器从会话目录向父目录查找 `.experience-strategy/runtime.sqlite3`；只有明确执行过 `runtime.py setup` 的项目才参与检查。v0.1 的 `state.json` 单独存在不会自动启用执行层。

卸载本适配器的项目 hooks：

```sh
python3 adapters/codex/install.py --root /path/to/project --uninstall
```

这保留体验历史和运行数据库，也保留其他 hooks。不要同时安装项目 hooks 和下方的插件 hooks，以免重复接收生命周期通知。

## 作为原生插件分发

根目录 `plugin.json` 使用 Agent Plugins schema，通过 `extensions.com.openai.hooks` 引用 `hooks/hooks.json`。插件 hook 命令使用 Codex 提供的 `${PLUGIN_ROOT}`，因此安装目录改变不会破坏插件内引用。

可按[官方本地插件步骤](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually)将整个仓库作为一个插件加入已有的本地 / 仓库 marketplace；启用插件后同样需要审核 hooks，并对目标项目执行上面的 `init` / `setup`。本仓库没有替用户改写全局 marketplace 或 trust 设置。

这属于本地或仓库分发的插件。官方当前不接受含生命周期 hooks 的插件进入公开插件目录；公开 GitHub 仓库和官方插件目录发布是两件事。

## 实际触发点

| Codex 事件 | 本适配器的作用 |
|---|---|
| `SessionStart` | 首次、恢复、fork、clear 和 compact 后重新注入持久体验状态 |
| `UserPromptSubmit` | 登记这一轮的体验影响判断，提供历史目标与待检 |
| `PreToolUse` | 注入已记录的约束；不拦截工具权限或强制批准每次写入 |
| `PostToolUse` | 由共享运行时比较配置范围内的文件快照，登记变化 |
| `Stop` | 待检未确认时返回一次有预算的继续请求；已续跑标志阻止循环 |
| `Interrupt` / `SessionEnd` | 记录停止状态，保留未决项；不阻止用户取消或重启会话 |

原始提示词、工具参数和聊天记录不会传给运行时。工具名、会话 / 轮次标识和事件标识会参与本地执行记录；项目状态仍包含你明确记录的目标、证据和判断。

模型收到注入内容后需要实际读取产物、判断影响，并用 `runtime.py checkpoint` 提交模板。直接调用底层 `harness.py commit` 不会清除执行层待检。检查可以有理由地选择 `depth: none`；程序能校验版本和回执，不能替你证明分析正确。

适配器故障会产生明确的未验证警告并允许宿主继续，不会假装通过，也不会制造无限续跑。某些专用工具路径可能不经过通用 hooks；结束前快照能补获配置范围内的文件变化，但无法覆盖仅发生在外部界面 / 服务中的变化。外部反馈需要交给 Agent，并纳入观察和证据。

## 验证范围与真实实验

运行适配器工程测试：

```sh
python3 -m unittest discover -s adapters/codex -p 'test_*.py' -v
```

原有 19 项测试覆盖事件协议、项目 opt-in、上下文注入、续跑限制、停止语义、故障提示、安装合并与卸载。其中两项通过真实子进程串联 `hook.py → runtime.py → SQLite / state.json`，验证文件变化、checkpoint 确认、中断后恢复；事件输入仍是 fixtures，不能证明你的 Codex 已信任或执行这些 hooks。

另有 2 项角色原型测试覆盖开启案件后的角色发现、交接后上下文更新，以及角色状态出错时普通待检继续可见。另有 1 项覆盖创作阶段的 Execution 交接与用户效果状态。当前合计 22 项。

v0.2.0 发布时已使用本地 `codex-cli 0.162.0-alpha.2` 的真实 app-server `hooks/list` 检查：通过临时 `-c` 参数传入生成的 inline hooks，7 个事件均被解析和发现、无错误，状态均为 `untrusted`。这验证原生配置解析与发现，没有授予信任、执行 hooks 或调用模型，也没有验证项目配置层的信任。可信 hooks 下的真实模型旅程仍需要外测。完整记录以根目录 [VALIDATION.md](../../VALIDATION.md) 为准。

首次人工外测建议完成这一条旅程：

1. 审核 hooks 后开始任务，检查 runtime context 是否出现新会话的实际事件与待检。
2. 让 Agent 修改一个 watch 范围内的交互文件，确认它收到检查上下文，并提交当前快照的 checkpoint。
3. 在一轮受控测试中暂不提交 checkpoint，观察 Stop 是否请求一次补检，且不会无限继续。
4. 中断尚未完成的检查，再恢复会话，确认待检仍在；查看旧 checkpoint 不能清除后续变化。
5. 记录是否真的发现新的体验问题、建议是否被采纳、额外耗时与误报，按回传模板提交。

安装配置、发现 hooks、脚本测试、真实宿主触发、模型完成检查、体验改善是不同验证层级，回传时请分别记录。

## 在当前项目接续设计角色

先在项目工具目录以 `python3 scripts/engine.py open --root PROJECT --input case.json` 显式开启个案（Python 3.9+）。已有 hooks 会在正常会话事件中列出该根的个案、版本和当前角色；没有个案时，原来的体验检查照常。显示的项目根与目标产品不一致时，先核对，不猜测父子目录之间的关系。

在宿主终端读取 `python3 scripts/engine.py context --root PROJECT --case-id CASE`：读取角色卡、允许的输出及历史，再通过 `python3 scripts/engine.py submit --root PROJECT --input result.json` 交回一份角色结果。提交包含该个案的 `case_id`、`binding`、`expected_revision`、新的 `request_id`、`role`、`output`；不自行递增 revision，不把 claim 当已验证事实。角色是当前宿主执行的职责，不会启动四个模型，也不证明多个独立评审者。等待真人、等待负责人时保留状态，下次确有新证据再继续。

角色交接与原有体验 checkpoint 是两件事：前者推进个案，后者确认普通待检事项。它们不互相确认，个案本身不会触发额外 Stop 或更改权限。

创建新案时显式传 task_stage。创作 case 的 hooks 会带回下一角色和用户效果状态，Execution 在案内指定目录交付候选，Measurement 交回检查结果。用 context 读取每一步的模板。
