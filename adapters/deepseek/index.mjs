import { execFile, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, dirname, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { createUserMessage } from '@deepseek-ai/dsh-llm';

export const name = 'experience-strategy-harness';
export const inject = ['agents', 'tools', 'workingDirectory'];

const OWN_TOOLS = new Set(['experience_context', 'experience_checkpoint', 'experience_roles', 'experience_role_submit']);
const MAX_BUFFER = 4 * 1024 * 1024;

function parseResult(stdout, stderr, status) {
  let value;
  try { value = JSON.parse(stdout); } catch {
    throw new Error(`Experience runtime returned invalid JSON (exit ${status}): ${String(stderr).slice(0, 800)}`);
  }
  if (status !== 0 || value?.ok !== true) {
    throw new Error(`Experience runtime failed: ${JSON.stringify(value).slice(0, 1600)}`);
  }
  return value;
}

function makeRuntime(config) {
  const runtime = config.runtimePath ?? fileURLToPath(new URL('./scripts/runtime.py', import.meta.url));
  const python = config.python ?? 'python3';
  const timeout = config.timeoutMs ?? 10000;
  if (!isAbsolute(runtime) || !existsSync(runtime)) {
    throw new Error('Experience runtime is missing. Run node adapters/deepseek/build.mjs, or configure an absolute runtimePath.');
  }
  if (typeof python !== 'string' || !python || !Number.isInteger(timeout) || timeout < 100 || timeout > 60000) {
    throw new Error('Experience plugin requires a Python executable and timeoutMs between 100 and 60000.');
  }
  function args(command, root) { return [runtime, command, '--root', root]; }
  function sync(command, root, input, timeoutOverride) {
    const result = spawnSync(python, args(command, root), {
      input: input === undefined ? undefined : JSON.stringify(input),
      encoding: 'utf8', timeout: timeoutOverride ?? timeout, killSignal: 'SIGKILL', maxBuffer: MAX_BUFFER, windowsHide: true,
    });
    if (result.error) throw result.error;
    return parseResult(result.stdout, result.stderr, result.status);
  }
  async function run(command, root, input, signal) {
    return runArgv(args(command, root), input, signal);
  }
  async function roleRun(command, root, input, signal, caseId) {
    const argv = [join(dirname(runtime), 'engine.py'), command, '--root', root];
    if (caseId !== undefined) argv.push(`--case-id=${caseId}`);
    return runArgv(argv, input, signal);
  }
  async function runArgv(argv, input, signal) {
    if (signal?.aborted) throw signal.reason ?? new Error('Aborted');
    return new Promise((resolve, reject) => {
      const child = execFile(python, argv, {
        encoding: 'utf8', timeout, maxBuffer: MAX_BUFFER, windowsHide: true,
        ...(signal ? { signal } : {}),
      }, (error, stdout, stderr) => {
        if (signal?.aborted) { reject(signal.reason ?? error ?? new Error('Aborted')); return; }
        if (error && typeof error.code !== 'number') { reject(error); return; }
        try { resolve(parseResult(stdout, stderr, error?.code ?? 0)); } catch (failure) { reject(failure); }
      });
      child.stdin.on('error', () => { /* The completion callback reports a failed child. */ });
      child.stdin.end(input === undefined ? undefined : JSON.stringify(input));
    });
  }
  return { run, sync, roleRun };
}

function contextMessage(text) {
  return createUserMessage({
    content: [{ type: 'text', text }],
    source: { kind: 'experience-strategy-harness' },
  });
}

function contextKey(result) {
  // Templates carry a fresh request_id on every read; that is not a context change.
  return result.context_key ?? JSON.stringify([result.snapshot, result.revision, result.pending_ids, result.warning, result.watch]);
}

export function apply(ctx, config = {}) {
  const runtime = makeRuntime(config);
  const active = new Map();

  function binding(agent) {
    const root = ctx.workingDirectory.get(agent.session);
    let current = active.get(agent);
    if (!current || current.root !== root) {
      current?.removeAbort?.();
      current = { root, turn: '0', stopCount: 0, forced: false, lastContextKey: '', failure: '' };
      active.set(agent, current);
    }
    return current;
  }
  function optedIn(agent) {
    return existsSync(join(binding(agent).root, '.experience-strategy', 'runtime.sqlite3'));
  }
  function payload(agent, event, eventId, extra = {}) {
    return {
      host: 'deepseek', session_id: String(agent.session.id),
      turn_id: binding(agent).turn, event_id: eventId, event, ...extra,
    };
  }
  function noteFailure(agent, error) {
    const current = binding(agent);
    current.failure = `Experience strategy checkpoint failed: ${String(error)}. Coverage is unknown; preserve pending work and report this limitation. Do not claim the experience review passed.`;
    ctx.logger.warn(current.failure);
    return current.failure;
  }
  function remember(agent, result) {
    binding(agent).failure = '';
    return result;
  }
  async function event(agent, type, id, extra, signal) {
    return remember(agent, await runtime.run('event', binding(agent).root, payload(agent, type, id, extra), signal));
  }
  function eventSync(agent, type, id, extra) {
    const deadline = ['interrupt', 'session-end'].includes(type) ? 1000 : undefined;
    try { return remember(agent, runtime.sync('event', binding(agent).root, payload(agent, type, id, extra), deadline)); }
    catch (error) { noteFailure(agent, error); return undefined; }
  }
  function instruction(result) {
    if (!result?.enabled || !result.context) return '';
    return ['Experience Strategy Harness is active for this project.', result.context,
      result.warning ?? '',
      result.roles?.cases?.length ? 'Use experience_roles with the relevant case_id to read its role brief and template. Use experience_role_submit only for that active role; the project and case binding come from the host and case record. Waiting is an acceptable end state.' : '',
      'Use experience_context to retrieve the exact checkpoint_template; fill it with evidence from this task and submit it through experience_checkpoint. Do not invent observations, user approval, or verification results.',
      'A committed checkpoint records the review; it does not prove product quality or human acceptance.',
    ].filter(Boolean).join('\n\n');
  }

  ctx.on('agent/created', async ({ agent, source, signal }) => {
    if (!optedIn(agent)) return;
    try {
      const result = await event(agent, 'session-start', `created:${source}:${randomUUID()}`, {}, signal);
      const text = instruction(result);
      if (text) agent.inject(contextMessage(text));
    } catch (error) {
      if (signal?.aborted) throw error;
      agent.inject(contextMessage(noteFailure(agent, error)));
    }
  });

  ctx.on('agent/pre-step', async ({ agent, turn, signal }, next) => {
    const downstream = await next();
    if (downstream.kind !== 'enter' || !optedIn(agent) || signal.aborted) return downstream;
    const current = binding(agent);
    let result;
    let newTurn = false;
    try {
      if (current.turn !== String(turn)) {
        newTurn = true;
        current.turn = String(turn);
        current.stopCount = 0;
        current.forced = false;
        current.removeAbort?.();
        const interrupted = () => {
          eventSync(agent, 'interrupt', `interrupt:${turn}`, {});
        };
        signal.addEventListener('abort', interrupted, { once: true });
        current.removeAbort = () => signal.removeEventListener('abort', interrupted);
        result = await event(agent, 'turn-start', `turn:${turn}`, {}, signal);
      } else {
        result = remember(agent, await runtime.run('context', current.root, undefined, signal));
      }
      const text = instruction(result);
      const key = contextKey(result);
      if (!text || (!newTurn && key === current.lastContextKey)) return downstream;
      current.lastContextKey = key;
      return { ...downstream, messages: [...downstream.messages, contextMessage(text)] };
    } catch (error) {
      if (signal.aborted) throw error;
      return { ...downstream, messages: [...downstream.messages, contextMessage(noteFailure(agent, error))] };
    }
  });

  ctx.on('tools/pre-execute', async (exec, next) => {
    if (exec.agent && !OWN_TOOLS.has(exec.name) && optedIn(exec.agent) && !exec.signal.aborted) {
      try {
        const result = await event(exec.agent, 'before-tool', `before:${exec.callId}`, { tool_name: exec.name }, exec.signal);
        const current = binding(exec.agent);
        const text = instruction(result);
        const key = contextKey(result);
        if (text && key !== current.lastContextKey) {
          current.lastContextKey = key;
          exec.agent.inject(contextMessage(text));
        }
      }
      catch (error) {
        if (exec.signal.aborted) throw error;
        exec.agent.inject(contextMessage(noteFailure(exec.agent, error)));
      }
    }
    // Preserve the host's permission decision. This is a review checkpoint, not an authorization bypass.
    return next();
  });

  ctx.on('tools/result', (exec) => {
    if (exec.agent && !OWN_TOOLS.has(exec.name) && optedIn(exec.agent)) {
      // This official event is synchronous. Persist the short event before returning;
      // no model request or unawaited write is launched from this callback.
      if (!eventSync(exec.agent, 'tool-result', `result:${exec.callId}`, { tool_name: exec.name })) {
        exec.agent.inject(contextMessage(binding(exec.agent).failure));
      }
    }
    return undefined;
  });

  ctx.on('agent/turn-stopping', async ({ agent, turn, signal }) => {
    if (signal.aborted || !optedIn(agent)) return;
    const current = binding(agent);
    try {
      const result = await event(agent, 'stop', `stop:${turn}:${current.stopCount++}`, { continuation: current.forced }, signal);
      if (result.enabled && result.block_stop && !current.forced && !signal.aborted) {
        current.forced = true;
        agent.steer(contextMessage(`Experience review is still pending. Complete one evidence-based checkpoint before finishing.\n\n${instruction(result)}`));
      } else if (result.warning) {
        // Do not manufacture an infinite turn. The durable pending queue is retained.
        ctx.logger.warn(result.warning);
      }
    } catch (error) {
      if (signal.aborted) return;
      const message = noteFailure(agent, error);
      if (!current.forced) {
        current.forced = true;
        agent.steer(contextMessage(message));
      }
    }
  });

  ctx.on('agent/error', ({ agent, turn }) => {
    if (optedIn(agent)) eventSync(agent, 'interrupt', `error:${turn}`, {});
  });
  ctx.on('agent/disposed', ({ agent }) => {
    const current = active.get(agent);
    if (!current) return;
    if (optedIn(agent)) eventSync(agent, 'session-end', `disposed:${randomUUID()}`, {});
    current.removeAbort?.();
    active.delete(agent);
  });
  ctx.effect(() => () => {
    for (const current of active.values()) current.removeAbort?.();
    active.clear();
  });

  const output = {
    schema: { type: 'object', additionalProperties: true },
    render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
  };
  ctx.tools.register({
    name: 'experience_context',
    description: 'Read this project\'s durable experience goals, pending reviews, current snapshot and exact checkpoint_template. Does not close a review.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output,
    async execute(args, exec) {
      if (!exec.agent || !args || typeof args !== 'object' || Array.isArray(args) || Object.keys(args).length) {
        throw new Error('experience_context requires an agent and empty arguments.');
      }
      return runtime.run('context', binding(exec.agent).root, undefined, exec.signal);
    },
  }, { when: ({ agent }) => optedIn(agent) });
  ctx.tools.register({
    name: 'experience_checkpoint',
    description: 'Submit the filled checkpoint_template obtained from experience_context. Uses the host-owned project directory; rejects stale snapshots or unsupported closure evidence.',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        pending_ids: { type: 'array', items: { type: 'string' } },
        snapshot: { type: 'string' },
        checkpoint: { type: 'object', additionalProperties: true },
      },
      required: ['pending_ids', 'snapshot', 'checkpoint'],
    },
    output,
    async execute(args, exec) {
      if (!exec.agent || !args || typeof args !== 'object' || Array.isArray(args)) throw new Error('Checkpoint requires an agent and object arguments.');
      if (Object.keys(args).some(key => !['pending_ids', 'snapshot', 'checkpoint'].includes(key))) throw new Error('Unknown checkpoint fields.');
      return runtime.run('checkpoint', binding(exec.agent).root, args, exec.signal);
    },
  }, { when: ({ agent }) => optedIn(agent) });
  const roleScope = ({ agent }) => optedIn(agent) && existsSync(join(binding(agent).root, '.experience-strategy', 'engine.sqlite3'));
  ctx.tools.register({
    name: 'experience_roles',
    description: 'List explicitly opened design cases; pass case_id for the next role brief, evidence contract, binding and revision. Read only.',
    parameters: { type: 'object', additionalProperties: false, properties: { case_id: { type: 'string', minLength: 1 } } },
    output,
    async execute(args, exec) {
      if (!exec.agent || !args || typeof args !== 'object' || Array.isArray(args) ||
          Object.keys(args).some(k => k !== 'case_id') ||
          ('case_id' in args && (typeof args.case_id !== 'string' || !args.case_id))) {
        throw new Error('experience_roles accepts only an optional case_id and uses the host session project.');
      }
      return runtime.roleRun('context', binding(exec.agent).root, undefined, exec.signal, args.case_id);
    },
  }, { when: roleScope });
  ctx.tools.register({
    name: 'experience_role_submit',
    description: 'Submit a single role output from a current role brief. Does not acknowledge a runtime checkpoint, authorize implementation, or collect user evidence.',
    parameters: {
      type: 'object', additionalProperties: false, required: ['case_id', 'binding', 'expected_revision', 'request_id', 'role', 'output'],
      properties: {
        case_id: { type: 'string' }, binding: { type: 'string' }, expected_revision: { type: 'integer' },
        request_id: { type: 'string' }, role: { type: 'string', enum: ['strategist', 'critic', 'verifier', 'judge', 'execution', 'measurement', 'user_evidence'] },
        output: { type: 'object', additionalProperties: true },
      },
    },
    output,
    async execute(args, exec) {
      if (!exec.agent || !args || typeof args !== 'object' || Array.isArray(args)) throw new Error('Role submission requires an agent and object arguments.');
      return runtime.roleRun('submit', binding(exec.agent).root, args, exec.signal);
    },
  }, { when: roleScope });
}
