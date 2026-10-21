// Run with: node --test tests/test_connect.mjs (requires pi on PATH).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';

const piEntry = realpathSync(execFileSync('which', ['pi'], { encoding: 'utf8' }).trim());
const requirePi = createRequire(piEntry);
const sdkEntry = resolve(piEntry, '../index.js');
const { createJiti } = requirePi('jiti');
const aiEntry = requirePi.resolve.paths('@earendil-works/pi-ai')
  .map(base => resolve(base, '@earendil-works/pi-ai/dist/index.js')).find(existsSync);
assert.ok(aiEntry, 'pi-ai must be installed alongside pi');
const jiti = createJiti(import.meta.url, {
  alias: { '@earendil-works/pi-ai': aiEntry, '@earendil-works/pi-coding-agent': sdkEntry },
});
const { ModelRuntime, SettingsManager } = await jiti.import(sdkEntry);
assert.equal(typeof ModelRuntime?.create, 'function', 'tests require pi 1.3 or later');
const extension = await jiti.import(resolve('pilot/pi_extensions/pilot-connect.ts'), { default: true });

function setup({ reasoning = true, thinkingLevelMap } = {}) {
  const commands = {};
  const handlers = {};
  const settings = SettingsManager.inMemory();
  SettingsManager.create = () => settings;
  let level = 'medium';
  const notices = [];
  const inputs = [];
  const model = { provider: 'openrouter', id: 'vendor/model', reasoning, thinkingLevelMap };
  const auth = {
    saved: [],
    async login(provider, type, interaction) {
      assert.equal(type, 'api_key');
      const key = await interaction.prompt({ type: 'secret', message: 'API key' });
      this.saved.push([provider, { type: 'api_key', key }]);
    },
  };
  ModelRuntime.create = async () => auth;
  const ctx = {
    cwd: '/test-workspace',
    model,
    ui: {
      notify: (...args) => notices.push(args),
      input: async () => inputs.shift(),
      select: async () => inputs.shift(),
      confirm: async () => false,
    },
    modelRegistry: {
      getAvailable: () => [model],
      find: (provider, id) => ctx.modelRegistry.getAvailable().find(m => m.provider === provider && m.id === id),
      getProviderAuthStatus: () => ({ configured: false }),
      refresh() {},
    },
  };
  const pi = {
    on: (name, handler) => handlers[name] = handler,
    registerCommand: (name, command) => commands[name] = command.handler,
    getThinkingLevel: () => level,
    setThinkingLevel: value => level = value,
    setModel: async value => { ctx.model = value; return true; },
  };
  extension(pi);
  return { commands, handlers, settings, ctx, pi, auth, notices, inputs, level: () => level };
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
  s.ctx.ui.input = async () => ' secret ';
  s.ctx.ui.select = async (title, options) => {
    if (title.startsWith('Select model')) {
      assert.deepEqual(options, ['vendor/model']);
      return 'vendor/model';
    }
    assert.ok(options.includes('low'));
    return 'low';
  };
  await s.commands.connect('openrouter', s.ctx);
  assert.deepEqual(s.auth.saved, [['openrouter', { type: 'api_key', key: 'secret' }]]);
  assert.equal(s.level(), 'low');
  assert.ok(!JSON.stringify(s.notices).includes('secret'));
});

test('cancelled key input leaves credentials untouched', async () => {
  const s = setup();
  await s.commands.connect('openrouter', s.ctx);
  assert.equal(s.auth.saved.length, 0);
  assert.equal(s.notices.at(-1)[1], 'error');
});

test('OpenAI subscription delegates to native OAuth with headless callbacks', async () => {
  const s = setup();
  let loggedIn = false;
  s.auth.login = async (provider, type, interaction) => {
    assert.equal(type, 'oauth');
    assert.equal(provider, 'openai-codex');
    s.inputs.push('Device code login (headless)');
    assert.equal(await interaction.prompt({ type: 'select', message: 'Login method', options: [
      { id: 'device', label: 'Device code login (headless)' },
    ] }), 'device');
    interaction.notify({ type: 'device_code', verificationUri: 'https://example.test/login', userCode: 'ABCD' });
    assert.ok(interaction.signal instanceof AbortSignal);
    loggedIn = true;
  };
  await s.commands.connect('openai-codex', s.ctx);
  assert.ok(loggedIn);
  assert.ok(s.notices.some(([text]) => text.includes('ABCD')));
});


test('registry refresh is awaited before listing connected models', async () => {
  const s = setup();
  let refreshed = false;
  s.ctx.modelRegistry.refresh = async () => {
    await new Promise(resolve => setTimeout(resolve, 5));
    refreshed = true;
  };
  const available = s.ctx.modelRegistry.getAvailable;
  s.ctx.modelRegistry.getAvailable = () => {
    assert.ok(refreshed);
    return available();
  };
  s.inputs.push('secret', 'vendor/model', 'low');
  await s.commands.connect('openrouter', s.ctx);
  assert.equal(s.level(), 'low');
});


test('model dialog offers available IDs as buttons, without text input', async () => {
  const s = setup();
  s.ctx.ui.input = async () => assert.fail('model selection must use buttons');
  s.ctx.ui.select = async (title, options) => {
    assert.match(title, /Select model \(openrouter\)/);
    assert.deepEqual(options, ['vendor/model']);
    return options[0];
  };
  await s.commands.model('', s.ctx);
  assert.ok(s.notices.some(([text]) => text.startsWith('Model: openrouter/vendor/model')));
});

test('large model catalog has paged buttons with forward and back navigation', async () => {
  const s = setup();
  s.ctx.modelRegistry.getAvailable = () => Array.from({ length: 15 }, (_, i) => ({
    provider: 'openai-codex', id: `model-${i}`, reasoning: true,
  }));
  let page = 0;
  s.ctx.ui.select = async (title, options) => {
    assert.ok(options.length <= 8);
    assert.match(title, /openai-codex/);
    if (page++ === 0) {
      assert.ok(options.includes('model-0'));
      return 'Next →';
    }
    if (page === 2) {
      assert.ok(options.includes('model-6'));
      return '← Previous';
    }
    assert.ok(options.includes('model-0'));
    return 'model-2';
  };
  await s.commands.model('', s.ctx);
  assert.equal(s.ctx.model.id, 'model-2');
  assert.equal(s.ctx.model.provider, 'openai-codex');
});

test('model dialog lets user select a connected provider before its models', async () => {
  const s = setup();
  s.ctx.modelRegistry.getAvailable = () => [
    s.ctx.model, { provider: 'openai-codex', id: 'subscription-model', reasoning: true },
  ];
  s.inputs.push('openai-codex', 'subscription-model');
  await s.commands.model('', s.ctx);
  assert.equal(s.ctx.model.provider, 'openai-codex');
  assert.equal(s.ctx.model.id, 'subscription-model');
});

test('cancelled model picker leaves current model unchanged', async () => {
  const s = setup();
  const original = s.ctx.model;
  await s.commands.model('', s.ctx);
  assert.equal(s.ctx.model, original);
  assert.equal(s.notices.length, 0);
});


test('model and thinking selections are stored together in native pi settings', async () => {
  const s = setup();
  await s.commands.model('openrouter/vendor/model', s.ctx);
  await s.commands.thinking('low', s.ctx);
  const saved = s.settings.getGlobalSettings();
  assert.equal(saved.defaultProvider, 'openrouter');
  assert.equal(saved.defaultModel, 'vendor/model');
  assert.equal(saved.defaultThinkingLevel, 'low');
  await s.commands.thinking('invalid', s.ctx);
  assert.deepEqual(s.settings.getGlobalSettings(), saved);
});

for (const reason of ['startup', 'new', 'resume', 'reload', 'fork']) {
  test(`saved selection wins over the initial runtime model on ${reason}`, async () => {
    const s = setup();
    await s.commands.model('openrouter/vendor/model', s.ctx);
    await s.commands.thinking('low', s.ctx);
    s.ctx.model = { provider: 'startup-provider', id: 'startup-model', reasoning: true };
    s.pi.setThinkingLevel('high');

    await s.handlers.session_start({ reason }, s.ctx);

    assert.equal(s.ctx.model.provider, 'openrouter');
    assert.equal(s.ctx.model.id, 'vendor/model');
    assert.equal(s.level(), 'low');
  });
}

test('startup defaults remain active until the first saved selection', async () => {
  const s = setup();
  const original = s.ctx.model;
  await s.handlers.session_start({ reason: 'startup' }, s.ctx);
  assert.equal(s.ctx.model, original);
  assert.equal(s.level(), 'medium');
  assert.equal(s.notices.length, 0);
});

test('a failed model change does not overwrite the saved selection', async () => {
  const s = setup();
  await s.commands.model('openrouter/vendor/model', s.ctx);
  const saved = s.settings.getGlobalSettings();
  s.pi.setModel = async () => false;
  await s.commands.model('openrouter/vendor/model', s.ctx);
  assert.deepEqual(s.settings.getGlobalSettings(), saved);
  assert.equal(s.notices.at(-1)[1], 'error');
});

test('an unavailable saved provider reports a restoration error', async () => {
  const s = setup();
  await s.commands.model('openrouter/vendor/model', s.ctx);
  s.ctx.modelRegistry.find = () => undefined;
  await s.handlers.session_start({ reason: 'new' }, s.ctx);
  assert.match(s.notices.at(-1)[0], /Could not restore saved model/);
  assert.equal(s.notices.at(-1)[1], 'error');
});


test('model changes preserve the chosen thinking level instead of stale runtime defaults', async () => {
  const s = setup();
  await s.commands.thinking('low', s.ctx);
  s.pi.setModel = async value => {
    s.ctx.model = value;
    s.pi.setThinkingLevel('high'); // pi's runtime still has the old CLI default.
    return true;
  };
  await s.commands.model('openrouter/vendor/model', s.ctx);
  assert.equal(s.level(), 'low');
  assert.equal(s.settings.getGlobalSettings().defaultThinkingLevel, 'low');
});


test('a settings write failure is reported without claiming the selection was saved', async () => {
  const s = setup();
  s.settings.drainErrors = () => [{ message: 'write failed' }];
  await s.commands.thinking('low', s.ctx);
  assert.match(s.notices.at(-1)[0], /could not be saved/);
  assert.equal(s.notices.at(-1)[1], 'error');
});
