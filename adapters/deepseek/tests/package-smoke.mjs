// Run against an installed tarball: node package-smoke.mjs /path/to/node_modules/dsh-experience-strategy-harness
import assert from 'node:assert/strict';
import { readFile, mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';

if (!process.argv[2]) throw new Error('Pass the installed tarball package directory.');
const packageRoot = resolve(process.argv[2]);
const require = createRequire(join(packageRoot, 'package.json'));
const load = name => import(pathToFileURL(require.resolve(name)).href);
const manifest = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
assert.equal(manifest.engines.dsh, '0.2.2-rc.3');
const { parse } = await load('yaml');
const patch = parse(await readFile(join(packageRoot, manifest.dsh.bundle.patch), 'utf8'));
assert.equal(patch.length, 1);
const [row] = patch[0].insert;
assert.equal(row.name, manifest.name);
for (const path of ['scripts/runtime.py', 'scripts/harness.py', 'SKILL.md', 'references/state-protocol.md', 'references/runtime-protocol.md']) {
  assert.ok((await readFile(join(packageRoot, path))).length > 0, `${path} must be packaged`);
}
const { Context } = await load('@deepseek-ai/cordis');
const { default: Loader } = await load('@deepseek-ai/cordis-plugin-loader');
const { default: LlmRuntime, LlmAdapter, createUserMessage } = await load('@deepseek-ai/dsh-llm');
const { default: SessionStore } = await load('@deepseek-ai/dsh-session');
const { default: SessionProjectionRegistry } = await load('@deepseek-ai/dsh-session-projection');
const { default: SystemPrompt } = await load('@deepseek-ai/dsh-system-prompt');
const { default: ToolRuntime } = await load('@deepseek-ai/dsh-tools');
const NativeToolExecutor = await load('@deepseek-ai/dsh-tool-executor-native');
const { default: AgentRegistry } = await load('@deepseek-ai/dsh-agent');
const { default: AgentLoop } = await load('@deepseek-ai/dsh-agent-loop');
const root = await mkdtemp(join(tmpdir(), 'experience-dsh-package-'));
const ctx = new Context();
let handle;
function cli(name, args) {
  const result = spawnSync(process.env.PYTHON ?? 'python3', [join(packageRoot, 'scripts', name), ...args], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr + result.stdout);
  return JSON.parse(result.stdout);
}
try {
  await mkdir(join(root, 'src'));
  await writeFile(join(root, 'src', 'fixture.txt'), 'Packaged runtime fixture.');
  cli('harness.py', ['init', '--root', root, '--project-id', 'package-smoke', '--goal', 'Exercise installed bundle', '--scope', 'Synthetic fixture', '--version', 'v1']);
  cli('runtime.py', ['setup', '--root', root, '--watch', 'src/**']);
  for (const service of [LlmRuntime, SessionStore, SessionProjectionRegistry, SystemPrompt, ToolRuntime, NativeToolExecutor, AgentRegistry]) await ctx.plugin(service);
  await ctx.plugin(AgentLoop, { agents: [] });
  ctx.provide('workingDirectory', { get: () => root });
  await ctx.plugin(Loader, { baseUrl: pathToFileURL(join(packageRoot, 'package.json')).href });
  await ctx.loader.create(row);
  await ctx.loader.await();
  class Fixture extends LlmAdapter {
    calls = 0;
    async resolveModel(provider, model) { return { provider, id: model, name: model }; }
    async *stream(options) {
      this.calls++;
      assert.ok(this.calls <= 2, 'installed plugin must not cause an unbounded loop');
      assert.match(JSON.stringify(options), /experience_checkpoint/);
      yield { type: 'block-start', index: 0, blockType: 'text' };
      yield { type: 'text-delta', index: 0, text: 'Fixture intentionally leaves review pending.' };
      yield { type: 'block-end', index: 0, block: { type: 'text', text: 'Fixture intentionally leaves review pending.' } };
      yield { type: 'finish', reason: { kind: 'stop' } };
    }
  }
  const provider = new Fixture();
  ctx.llm.registerAdapter(['fixture'], provider);
  handle = await ctx.agents.create({ sessionId: 'package-smoke-session', meta: { cwd: root }, agentOptions: { provider: 'fixture', model: 'fixture' } });
  handle.agent.followup(createUserMessage({ content: [{ type: 'text', text: 'Exercise the installed native plugin.' }], source: { kind: 'user' } }));
  await handle.agent.whenIdle();
  assert.equal(provider.calls, 2, 'tarball-loaded hook must force exactly one additional real host step');
  assert.equal(cli('runtime.py', ['context', '--root', root]).review_required, true);
  console.log(JSON.stringify({ ok: true, test: 'installed-tarball-official-loader-native-loop', dsh: '0.2.2-rc.3', model: 'deterministic-fixture', model_steps: provider.calls, pending_preserved: true }));
} finally {
  await handle?.dispose();
  await ctx.fiber.dispose();
  await rm(root, { recursive: true, force: true });
}
