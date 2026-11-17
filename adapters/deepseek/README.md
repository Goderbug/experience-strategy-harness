# DeepSeek Harness 原生执行层

这是 DeepSeek Harness (`dsh`) 的 **Cordis 插件 bundle**。安装到实际使用的宿主 profile 后，它通过生命周期事件运行体验检查；无需用户每轮重复提醒，也不另行调用 DeepSeek API。

兼容目标为 **DSH 0.2.2-rc.3**，Node.js ≥ 24.9，Python 3。接口基线见 [UPSTREAM.md](UPSTREAM.md)。开发预览接口变化快，本包用 `engines.dsh` 限定已验证版本；其他版本需要重新验证，不能直接放宽版本声明。

## 安装和启动

从仓库构建本地 bundle，在仓库根目录执行：

```sh
node adapters/deepseek/build.mjs
dsh plugin --profile web add ./adapters/deepseek
dsh --profile web --dump-config
dsh web
```

`--dump-config` 中应出现 `dsh-experience-strategy-harness` 层及 `experience-strategy-harness` 行。`web` 是这里的示例 profile；如果你的 CLI、Desktop 或 SDK 使用其他 profile，应把插件安装到那个 profile，并通过其正常启动入口重启。不要把“安装在一个 profile”当成所有宿主都已启用。

也可直接安装发布的独立 tarball；它内含运行脚本和方法文件，不依赖原仓库位置：

```sh
dsh plugin --profile web add ./dsh-experience-strategy-harness-0.3.0-alpha.2.tgz
```

该安装会在指定 profile 启用代码。项目还需要明确选择监测范围。以下命令从本仓库根目录运行，将路径与目标替换为实际项目；已有策略状态时跳过 `init`：

```sh
python3 scripts/harness.py init --root /absolute/path/to/project \
  --project-id my-project --goal '用户能够完成主要任务' \
  --scope '本次已授权的交互流程' --version baseline
python3 scripts/runtime.py setup --root /absolute/path/to/project \
  --watch 'src/**' --watch 'design/**'
```

从独立 tarball 解压目录运行相同 `scripts/` 命令也可完成 setup。随后在 DSH 中打开该项目根目录并新建或恢复会话。插件从 `ctx.workingDirectory.get(agent.session)` 取得项目；不使用宿主进程的默认目录，也不接受模型传入其他项目根目录。未 setup 的项目不会获得本插件的上下文、工具或强制续跑。

第一次运行时检查实际行为：模型能看到体验目标和待检查事项，工具列表出现 `experience_context` / `experience_checkpoint`；读取项目的 `runtime.py context` 可查看尚未完成的队列。只看到配置层不能证明该项目已接入。

## 宿主如何持续介入

| 宿主节点 | 实际行为 |
| --- | --- |
| `agent/created` | 读取已保存目标、问题和 pending 检查，注入首次或恢复上下文 |
| `agent/pre-step` | 新一轮建立检查；后续模型步骤按稳定状态键去重，状态变化才再注入 |
| `tools/pre-execute` | 记录检查节点并提供新增上下文；保留宿主已有权限判断 |
| `tools/result` | 在官方同步最终结果通知中保存短事件，比较所选文件内容快照 |
| `agent/turn-stopping` | 有漏检时向同一 Agent 的 inbox `steer`，默认最多强制续跑一次 |
| 用户中断 / `agent/error` | 保存中断事件；不因体验检查再次唤醒被用户停止的任务 |
| `agent/disposed` | 保存结束事件，清理进程内监听状态 |

工具 `experience_context` 返回真实状态和完整 `checkpoint_template`。Agent 检查实际材料、填写判断和证据后调用 `experience_checkpoint`；该工具验证快照、revision、问题关联及关闭证据后，才确认这批检查。底层 `harness.py commit` 本身不能确认执行层队列。

如果模型连续忽略检查，续跑达到上限后允许宿主结束，**pending 保留**，下次会话恢复；日志会提示本轮未清空。该限制避免无限循环。因此“宿主已检查触发条件”与“模型完成了有质量的体验分析”仍是两件事。

## 配置与故障

默认执行命令为 `python3`，每次核心调用最多 10 秒。需要调整时，在 profile 的用户 patch 层覆写已插入行：

```yaml
- id: experience-strategy-harness
  config:
    python: /absolute/path/to/python3
    timeoutMs: 15000
```

`runtimePath` 仅供开发或明确的自定义部署，必须为绝对路径；发布包默认使用随包的 `scripts/runtime.py`。同步 `tools/result` 调用会短暂占用宿主事件循环，因此应选择有界的源码/设计范围，不要监测整个磁盘或依赖目录。核心的文件数量和字节上限会拒绝过大范围。

核心错误会进入日志，并在仍运行的会话中提供给模型，明确检查覆盖未知；不会把异常视为通过，不会自动改变权限或删除锁。用户取消时只保存可恢复信息，不强制继续。中断与结束事件有独立的 1 秒进程截止时间；如果无法及时记录，留下日志并保留原 pending，不等待完整扫描或强制续跑。

这是一层**事件驱动的执行机制**。宿主关闭时不运行；图片像素、浏览器行为和真实用户反馈不会被文件哈希自动理解。Agent 仍需实际查看界面和执行验证，文件快照仅用于发现范围内的内容变化。所有模型调用仍由原来的 DSH 宿主处理；一次补检可能增加模型步数与费用。

## 可复现验证

在 `adapters/deepseek` 安装精确的测试依赖并执行：

```sh
npm ci --ignore-scripts
npm test
```

测试使用官方 Cordis、Session、工具执行器、AgentRegistry 和 AgentLoop **0.2.2-rc.3**，加一个确定性模型适配器。工作目录服务是固定目录测试替身；无网络、API key、付费模型或真实用户测试。

覆盖：停止时实际产生额外模型步骤；checkpoint 工具完成后结束；模型忽略后的有界结束；新宿主继续未决检查；原生工具修改真实临时文件后触发复查；未启用项目无影响；核心失败可见；用户取消不会被续跑覆盖。测试证明宿主事件接线与恢复机制，不证明模型判断质量或产品体验改善。

发布包另有安装验收脚本：先将 tarball 安装到带有上述测试依赖的隔离目录，再运行 `node tests/package-smoke.mjs /absolute/path/to/node_modules/dsh-experience-strategy-harness`。它从包的 `dsh.bundle.patch` 读取实际行，经官方 Cordis Loader 加载，使用包内 Python 脚本走真实 AgentLoop，并确认只补跑一次且未决检查仍被保存；不依赖源仓库的运行脚本。

## 原型：设计角色交接

在正常 `harness.py init` 和 `runtime.py setup` 完成后，用 `python3 scripts/engine.py open --root PROJECT --input case.json` 在目标项目开启个案（根须与 DSH 会话工作目录一致）。未创建个案数据库的项目只显示原来的体验检查工具。已开启个案时，多两个原生工具：

- `experience_roles({})` 只读列表；传 `{"case_id":"…"}` 读取当前角色、绑定标识、版本、历史、角色卡与输出模板。
- `experience_role_submit({case_id,binding,expected_revision,request_id,role,output})` 提交当前角色一份输出。根目录仅取自当前 DSH 会话，不由模型指定。它不会替普通 checkpoint 签收，更不等于采集到真人数据或授权设计上线。

已保存的角色进度会在下一次正常步骤/会话带回；等待真人时不会自动安排模型续跑。角色是同一宿主可执行的不同职责，不等同多个独立人员。打开个案与得到新证据后的显式恢复走随包的 engine CLI。常规待检与角色进度可同时出现，应分别判断。

创作案件通过同一组原生工具接续 critic、execution 和 measurement。以当前角色卡给定的目录、模板与版本为准，产物准备好后可结束。用户验证案件才调度 user_evidence。
