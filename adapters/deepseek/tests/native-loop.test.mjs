import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, copyFile, chmod, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';

// Official host packages, deterministic provider. No network, credentials or real model calls.
const adapterRoot = fileURLToPath(new URL('../', import.meta.url));
const sourceRoot = fileURLToPath(new URL('../../../', import.meta.url));
const dependencyRoot = process.env.ESH_DSH_TEST_HOME ? resolve(process.env.ESH_DSH_TEST_HOME) : adapterRoot;
const require = createRequire(join(dependencyRoot, 'package.json'));
const load = async name => import(pathToFileURL(require.resolve(name)).href);
const { Context } = await load('@deepseek-ai/cordis');
const { default: LlmRuntime, LlmAdapter, createUserMessage } = await load('@deepseek-ai/dsh-llm');
const { default: SessionStore } = await load('@deepseek-ai/dsh-session');
const { default: SessionProjectionRegistry } = await load('@deepseek-ai/dsh-session-projection');
const { default: SystemPrompt } = await load('@deepseek-ai/dsh-system-prompt');
const { default: ToolRuntime } = await load('@deepseek-ai/dsh-tools');
const NativeToolExecutor = await load('@deepseek-ai/dsh-tool-executor-native');
const { default: AgentRegistry } = await load('@deepseek-ai/dsh-agent');
const { default: AgentLoop } = await load('@deepseek-ai/dsh-agent-loop');
const tempModule = await mkdtemp(join(dependencyRoot, '.experience-native-test-'));
await copyFile(join(adapterRoot, 'index.mjs'), join(tempModule, 'index.mjs'));
const ExperiencePlugin = await import(pathToFileURL(join(tempModule, 'index.mjs')).href);
test.after(async () => { await rm(tempModule, { recursive: true, force: true }); });

const runtimePath = join(sourceRoot, 'scripts', 'runtime.py');
const harnessPath = join(sourceRoot, 'scripts', 'harness.py');
const python = process.env.PYTHON ?? 'python3';
function cli(script, args, input) {
  const result = spawnSync(python, [script, ...args], {
    input: input === undefined ? undefined : JSON.stringify(input), encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 0, `CLI failed: ${result.stderr}\n${result.stdout}`);
  return JSON.parse(result.stdout);
}
async function project(enabled = true) {
  const root = await mkdtemp(join(tmpdir(), 'experience-dsh-native-'));
  await mkdir(join(root, 'src'));
  await writeFile(join(root, 'src', 'view.txt'), 'Original task controls.\n');
  cli(harnessPath, ['init', '--root', root, '--project-id', 'dsh-native-test', '--goal', 'Keep the user task discoverable', '--scope', 'Synthetic fixture only', '--version', 'fixture-v1']);
  if (enabled) cli(runtimePath, ['setup', '--root', root, '--watch', 'src/**']);
  return root;
}
function textResponse(text) {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text },
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'finish', reason: { kind: 'stop' } },
  ];
}
function toolResponse(id, name, args) {
  const raw = JSON.stringify(args);
  return [
    { type: 'block-start', index: 0, blockType: 'tool-call' },
    { type: 'tool-call-delta', index: 0, id, name, argumentsDelta: raw },
    { type: 'block-end', index: 0, block: { type: 'tool-call', id, name, arguments: raw } },
    { type: 'finish', reason: { kind: 'tool-calls' } },
  ];
}
class ScriptedProvider extends LlmAdapter {
  requests = [];
  constructor(script) { super(); this.script = script; }
  async resolveModel(provider, model) { return { provider, id: model, name: model }; }
  async *stream(options) {
    this.requests.push(options);
    const step = this.script.shift();
    if (!step) throw new Error('Scripted provider exhausted: possible unbounded continuation.');
    for (const chunk of await step(options)) {
      if (options.signal?.aborted) throw options.signal.reason;
      yield chunk;
    }
  }
}
function filledCheckpoint(root) {
  const result = cli(runtimePath, ['context', '--root', root]);
  assert.ok(result.pending_ids.length > 0);
  const envelope = result.checkpoint_template;
  envelope.checkpoint.change = 'Inspect the current synthetic fixture and its recorded event.';
  envelope.checkpoint.depth = 'focused';
  envelope.checkpoint.reason = 'A lifecycle checkpoint became due.';
  envelope.checkpoint.summary = 'Synthetic test exercised protocol completion; no user experience outcome was measured.';
  envelope.checkpoint.next_action = 'Await a real project change or user feedback.';
  envelope.checkpoint.limitations = ['Scripted provider; not an independent design assessment.'];
  return envelope;
}
async function host(root, script, pluginConfig = {}) {
  const ctx = new Context();
  await ctx.plugin(LlmRuntime);
  await ctx.plugin(SessionStore);
  await ctx.plugin(SessionProjectionRegistry);
  await ctx.plugin(SystemPrompt);
  await ctx.plugin(ToolRuntime);
  await ctx.plugin(NativeToolExecutor);
  await ctx.plugin(AgentRegistry);
  await ctx.plugin(AgentLoop, { agents: [] });
  // Only the working-directory service is a fixture; the loop, events, inbox,
  // tools, provider dispatch and Session log are the official implementations.
  ctx.provide('workingDirectory', { get: () => root });
  const provider = new ScriptedProvider(script);
  ctx.llm.registerAdapter(['test-fixture'], provider);
  await ctx.plugin(ExperiencePlugin, { runtimePath, python, ...pluginConfig });
  const handle = await ctx.agents.create({
    sessionId: `native-test-${Math.random().toString(16).slice(2)}`,
    meta: { cwd: root }, agentOptions: { provider: 'test-fixture', model: 'scripted' },
  });
  return { ctx, provider, handle, agent: handle.agent };
}
async function run(agent, message = 'Evaluate this synthetic fixture.') {
  agent.followup(createUserMessage({ content: [{ type: 'text', text: message }], source: { kind: 'user' } }));
  await agent.whenIdle();
}
async function cleanup(h, root) {
  if (h) { await h.handle.dispose(); await h.ctx.fiber.dispose(); }
  await rm(root, { recursive: true, force: true });
}

test('native stop hook forces one real extra step, checkpoint commits, then host closes', async () => {
  const root = await project(); let h;
  try {
    h = await host(root, [
      async () => textResponse('First answer intentionally omitted the review.'),
      async options => {
        assert.match(JSON.stringify(options), /Experience review is still pending/);
        return toolResponse('checkpoint-1', 'experience_checkpoint', filledCheckpoint(root));
      },
      async () => textResponse('Checkpoint recorded; user validation remains absent.'),
    ]);
    await run(h.agent);
    assert.equal(h.provider.requests.length, 3);
    const state = cli(runtimePath, ['context', '--root', root]);
    assert.equal(state.review_required, false);
    assert.deepEqual(state.pending_ids, []);
    const events = h.agent.session.snapshotEvents();
    assert.equal(events.filter(item => item.type === 'tool/result').length, 1);
    assert.ok(events.some(item => item.type === 'user/message' && item.data.source?.kind === 'experience-strategy-harness'));
  } finally { await cleanup(h, root); }
});

test('ignored checkpoint cannot spin forever; pending survives a new host/session', async () => {
  const root = await project(); let h;
  try {
    h = await host(root, [async () => textResponse('Ignored.'), async () => textResponse('Ignored again.')]);
    await run(h.agent);
    assert.equal(h.provider.requests.length, 2);
    const before = cli(runtimePath, ['context', '--root', root]);
    assert.equal(before.review_required, true);
    await h.handle.dispose(); await h.ctx.fiber.dispose(); h = undefined;
    h = await host(root, [
      async options => {
        assert.match(JSON.stringify(options), /Experience Strategy Harness is active/);
        return toolResponse('checkpoint-resume', 'experience_checkpoint', filledCheckpoint(root));
      },
      async () => textResponse('Recovered the pending checkpoint.'),
    ]);
    await run(h.agent);
    assert.equal(cli(runtimePath, ['context', '--root', root]).review_required, false);
  } finally { await cleanup(h, root); }
});

test('actual watched file mutation through a native tool creates review work', async () => {
  const root = await project(); let h;
  try {
    h = await host(root, [
      async () => toolResponse('checkpoint-before', 'experience_checkpoint', filledCheckpoint(root)),
      async () => toolResponse('change-view', 'fixture_change_view', {}),
      async () => textResponse('Changed the fixture, intentionally omitted follow-up review.'),
      async () => toolResponse('checkpoint-after', 'experience_checkpoint', filledCheckpoint(root)),
      async () => textResponse('Change review recorded.'),
    ]);
    h.ctx.tools.register({
      name: 'fixture_change_view', description: 'Synthetic test writes one watched file.',
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
      async execute() { await writeFile(join(root, 'src', 'view.txt'), 'Changed control placement.\n'); return 'changed'; },
    });
    await run(h.agent);
    assert.equal(h.provider.requests.length, 5);
    assert.equal(cli(runtimePath, ['context', '--root', root]).review_required, false);
    const state = JSON.parse(await readFile(join(root, '.experience-strategy', 'state.json'), 'utf8'));
    assert.ok(state.checkpoints.length >= 2);
  } finally { await cleanup(h, root); }
});

test('unconfigured project has no injected context, tools, or forced continuation', async () => {
  const root = await project(false); let h;
  try {
    h = await host(root, [async options => {
      assert.doesNotMatch(JSON.stringify(options), /experience_checkpoint|Experience Strategy Harness is active/);
      return textResponse('Ordinary agent answer.');
    }]);
    await run(h.agent);
    assert.equal(h.provider.requests.length, 1);
  } finally { await cleanup(h, root); }
});

test('a runtime failure is visible to the model and cannot silently report clean coverage', async () => {
  const root = await project(); let h;
  try {
    h = await host(root, [
      async options => { assert.match(JSON.stringify(options), /Coverage is unknown/); return textResponse('Runtime unavailable.'); },
      async () => textResponse('Pending work was not declared complete.'),
    ], { python: 'experience-test-missing-python-executable' });
    await run(h.agent);
    assert.equal(h.provider.requests.length, 2);
    assert.equal(cli(runtimePath, ['context', '--root', root]).revision, 0);
  } finally { await cleanup(h, root); }
});

test('user cancellation is preserved and does not wake another review step', { timeout: 10000 }, async () => {
  const root = await project(); let h;
  try {
    const started = Promise.withResolvers();
    h = await host(root, [async options => {
      started.resolve();
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
      });
    }]);
    h.agent.followup(createUserMessage({ content: [{ type: 'text', text: 'Start then let me cancel.' }], source: { kind: 'user' } }));
    await started.promise;
    h.agent.cancel({ kind: 'user' });
    await h.agent.whenIdle();
    assert.equal(h.provider.requests.length, 1);
    assert.equal(cli(runtimePath, ['context', '--root', root]).review_required, true);
    assert.equal(h.agent.status, 'idle');
  } finally { await cleanup(h, root); }
});

test('a slow interrupt recorder cannot hold user cancellation for the configured long timeout', { timeout: 15000 }, async () => {
  const root = await project(); let h;
  try {
    const wrapper = join(root, 'slow-python');
    await writeFile(wrapper, '#!/usr/bin/env python3\nimport sys, json, time, subprocess\ndata = sys.stdin.buffer.read()\ntry:\n event = json.loads(data)\nexcept Exception:\n event = {}\nif event.get("event") == "interrupt":\n time.sleep(5)\nresult = subprocess.run([sys.executable, *sys.argv[1:]], input=data, capture_output=True)\nsys.stdout.buffer.write(result.stdout)\nsys.stderr.buffer.write(result.stderr)\nsys.exit(result.returncode)\n');
    await chmod(wrapper, 0o700);
    const started = Promise.withResolvers();
    h = await host(root, [async options => {
      started.resolve();
      return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true }));
    }], { python: wrapper, timeoutMs: 10000 });
    h.agent.followup(createUserMessage({ content: [{ type: 'text', text: 'Start a cancellable fixture.' }], source: { kind: 'user' } }));
    await started.promise;
    const before = performance.now();
    h.agent.cancel({ kind: 'user' });
    await h.agent.whenIdle();
    assert.ok(performance.now() - before < 2500, 'cancellation must use the short interrupt deadline');
    assert.equal(h.provider.requests.length, 1);
    assert.equal(cli(runtimePath, ['context', '--root', root]).review_required, true);
  } finally { await cleanup(h, root); }
});
