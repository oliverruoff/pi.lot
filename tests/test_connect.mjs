// Run with: node --test tests/test_connect.mjs (requires pi on PATH).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const requirePi = createRequire(realpathSync(execFileSync('which', ['pi'], { encoding: 'utf8' }).trim()));
const { createJiti } = requirePi('jiti');
const aiEntry = requirePi.resolve.paths('@earendil-works/pi-ai')
  .map(base => resolve(base, '@earendil-works/pi-ai/dist/index.js')).find(existsSync);
assert.ok(aiEntry, 'pi-ai must be installed alongside pi');
const jiti = createJiti(import.meta.url, {
  alias: { '@earendil-works/pi-ai': aiEntry },
});
const extension = await jiti.import(resolve('pilot/pi_extensions/pilot-connect.ts'), { default: true });

function setup({ reasoning = true, thinkingLevelMap } = {}) {
  const commands = {};
  let level = 'medium';
  const notices = [];
  const inputs = [];
  const model = { provider: 'openrouter', id: 'vendor/model', reasoning, thinkingLevelMap };
  const auth = { set() {}, async login() {} };
  const ctx = {
    model,
    ui: {
      notify: (...args) => notices.push(args),
      input: async () => inputs.shift(),
      select: async () => inputs.shift(),
      confirm: async () => false,
    },
    modelRegistry: {
      getAvailable: () => [model],
      getProviderAuthStatus: () => ({ configured: false }),
      authStorage: auth,
      refresh() {},
    },
  };
  const pi = {
    registerCommand: (name, command) => commands[name] = command.handler,
    getThinkingLevel: () => level,
    setThinkingLevel: value => level = value,
    setModel: async value => { ctx.model = value; return true; },
  };
  extension(pi);
  return { commands, ctx, pi, auth, notices, inputs, level: () => level };
}

test('valid thinking is applied; unknown or unsupported levels leave it unchanged', async () => {
  const s = setup({ thinkingLevelMap: { high: null } });
  await s.commands.thinking('low', s.ctx);
  assert.equal(s.level(), 'low');
  for (const value of ['high', 'xhigh', 'invalid']) {
    await s.commands.thinking(value, s.ctx);
    assert.equal(s.level(), 'low');
    assert.equal(s.notices.at(-1)[1], 'error');
    assert.match(s.notices.at(-1)[0], /Thinking unchanged/);
  }
});

test('non-reasoning model only allows off', async () => {
  const s = setup({ reasoning: false });
  await s.commands.thinking('low', s.ctx);
  assert.equal(s.level(), 'medium');
  await s.commands.thinking('off', s.ctx);
  assert.equal(s.level(), 'off');
});

test('thinking dialog cancellation does not change state', async () => {
  const s = setup();
  await s.commands.thinking('', s.ctx);
  assert.equal(s.level(), 'medium');
});

test('model uses full provider/id including nested OpenRouter ID', async () => {
  const s = setup();
  s.ctx.model = undefined;
  await s.commands.model('openrouter/vendor/model', s.ctx);
  assert.equal(s.ctx.model.id, 'vendor/model');
  await s.commands.model('missing/model', s.ctx);
  assert.equal(s.ctx.model.id, 'vendor/model');
  assert.equal(s.notices.at(-1)[1], 'error');
});

test('OpenRouter connect saves key and runs model/thinking selection', async () => {
  const s = setup();
  const stored = [];
  s.auth.set = (...args) => stored.push(args);
  s.inputs.push(' secret ', 'vendor/model', 'low');
  await s.commands.connect('openrouter', s.ctx);
  assert.deepEqual(stored, [['openrouter', { type: 'api_key', key: 'secret' }]]);
  assert.equal(s.level(), 'low');
  assert.ok(!JSON.stringify(s.notices).includes('secret'));
});

test('cancelled key input leaves credentials untouched', async () => {
  const s = setup();
  s.auth.set = () => assert.fail('must not store cancelled credentials');
  await s.commands.connect('openrouter', s.ctx);
  assert.equal(s.notices.length, 0);
});

test('OpenAI subscription delegates to native OAuth with headless callbacks', async () => {
  const s = setup();
  let loggedIn = false;
  s.auth.login = async (provider, callbacks) => {
    assert.equal(provider, 'openai-codex');
    s.inputs.push('Device code login (headless)');
    assert.equal(await callbacks.onSelect({ message: 'Login method', options: [
      { id: 'device', label: 'Device code login (headless)' },
    ] }), 'device');
    callbacks.onDeviceCode({ verificationUri: 'https://example.test/login', userCode: 'ABCD' });
    assert.ok(callbacks.signal instanceof AbortSignal);
    loggedIn = true;
  };
  await s.commands.connect('openai-codex', s.ctx);
  assert.ok(loggedIn);
  assert.ok(s.notices.some(([text]) => text.includes('ABCD')));
});
