# Runtime protocol v0.2

The runtime surrounds the existing v0.1 strategy-state tool. It supplies event routing, a durable queue, content versions, and a bounded stop gate. The host model performs the experience review; the runtime does not make its own model calls or validate the truth of a judgment.

## Project opt-in

Initialize the existing project with `scripts/harness.py init`, then run:

```sh
python3 scripts/runtime.py setup --root /path/to/project --watch 'src/**' --watch 'public/**' --max-continuations 1
```

Watch patterns are project-relative. Choose files that carry the relevant experience, such as UI code, flows, design specifications or exported artifacts. Content hashes identify additions, edits and deletions. A file hash is a version identity, not semantic understanding or a screenshot review. Common credential filenames, runtime data, dependency trees and symlink escapes are excluded or rejected; the filter is not a general secret detector. Scope limits fail visibly instead of silently pretending a partial snapshot is complete.

No configured project means adapters do nothing. Setup does not load or trust any host plugin. Loading a plugin does not itself opt every project in. Identical setup is safe to repeat; incompatible reconfiguration is rejected rather than resetting history.

## Host event envelope

`python3 scripts/runtime.py event --root PROJECT` accepts one JSON object on stdin:

```json
{
  "host": "codex",
  "session_id": "actual-host-session-id",
  "turn_id": "actual-host-turn-id",
  "event_id": "unique-native-event-identity",
  "event": "tool-result",
  "tool_name": "actual-tool-name"
}
```

Hosts are `codex` and `deepseek`. Events are `session-start`, `turn-start`, `before-tool`, `tool-result`, `stop`, `interrupt`, and `session-end`. Optional `continuation: true` marks a host's continuation, preventing another stop block. A stable `context_key` identifies the current review basis; unchanged tool events suppress duplicate context injection. An absent turn ID at session start is represented by an empty string. Do not send prompts, tool arguments, output text, transcripts or secrets to this interface.

A successful response exposes `enabled`, `context`, `review_required`, `block_stop`, `pending_ids`, `snapshot`, and `revision`. Enabled context also supplies `required_node` and `checkpoint_template`. Errors are structured and must be made visible by the host; an error is not a clean review.

`session-start` requests recovery. `turn-start` requests a lightweight relevance / pre-change judgment. `before-tool` supplies context, without rejecting product actions. `tool-result` and `stop` compare selected file content with the persisted baseline and enqueue an after-change check when it differs. Multiple observations can be reconciled in one checkpoint. `stop` may request continuation within the configured budget. Interruption retains pending items and prevents further continuation for the interrupted turn when its event is recorded. Interruption and session end use the cached snapshot and a short database wait; they do not scan files or replay strategy history. If recording fails, host cancellation still takes precedence.

The host's native event names and semantics are preserved in each adapter. In Codex, a Stop continuation can itself appear as another prompt/turn: `stop_hook_active` is a separate guard in addition to persisted budgets. In DSH, the plugin calls the official `agent.steer` mechanism from `agent/turn-stopping`.

## Judgment and confirmation

Read current context:

```sh
python3 scripts/runtime.py context --root /path/to/project
```

Inspect the actual changed artifact and current user request. Fill the returned template, preserving its `pending_ids` and content `snapshot`. The nested checkpoint follows [state-protocol.md](state-protocol.md); `project_version` is the runtime's `files:` snapshot identity. Submit the entire wrapper on stdin:

```sh
python3 scripts/runtime.py checkpoint --root /path/to/project < checkpoint.json
```

The wrapper contains `pending_ids`, `snapshot`, and `checkpoint`. The runtime validates current file identity, pending items, node and strategy revision, then calls the existing state validator. It acknowledges only the submitted pending items after a successful strategy commit. Direct `harness.py commit` remains available for portable use, but does not acknowledge runtime work.

Use a fresh `checkpoint.request_id` for new work. Retrying the exact same request is idempotent. A reused ID with changed content is a conflict. A stale snapshot requires renewed inspection, not merely replacing the hash. A stale revision requires reconciling the latest strategy state. New pending work must survive acknowledgment of older work.

`depth: none` is legitimate when the actual change has no relevant impact; record a concrete reason. The check is not required to invent an issue or alter the product. Conversely, a well-formed empty judgment is not proof of thorough analysis. This remains an external evaluation concern.

## Durability, failures and concurrency

Runtime state lives in project-local `.experience-strategy/runtime.sqlite3`; strategy records remain in `state.json`. SQLite serializes runtime events. The strategy helper keeps its existing atomic-write, revision and idempotency rules. The runtime handles retry after a strategy commit succeeds but before acknowledgment is durably recorded.

A process killed during the legacy strategy helper's write can leave its existing `write.lock`. This case fails visibly. Follow the original helper's recovery message: confirm the writer is no longer running before removing only the stale lock. The runtime does not guess whether another writer is alive or silently delete its lock.

After a failed or exhausted stop check, unresolved pending items remain available to the next session. The agent should report the remaining check rather than claim success. A finite continuation budget intentionally permits the turn to end with unresolved work; it prevents looping and is not an absolute release block.

The file scan cannot see edits made after its final snapshot until the next event. It cannot observe a remote site, Figma document, deployed build, user session or background process merely because a local file changed. Watch the relevant local evidence and explicitly use host tools for the actual artifact. Neither adapter wakes a stopped host or supplies a background model service.

## Native mapping and provenance

- Codex: [official Hooks](https://learn.chatgpt.com/docs/hooks) and [plugin packaging](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks), consulted 2026-11-16. Hooks require user trust. This package does not bypass it.
- DeepSeek Harness: [official source at commit 39163dd](https://github.com/deepseek-ai/deepseek-harness/tree/39163dd30f703a79079e2d2446545cff3c453738), `0.2.2-rc.3`. See adapter documentation for precise plugin, tool, message and lifecycle interfaces.

Only the host events needed by this MVP are automatically mapped. Rich feedback classification, intake refinement and handoff reasoning still belong to the host's strategy work; a session-end notification cannot run another review model by itself.
