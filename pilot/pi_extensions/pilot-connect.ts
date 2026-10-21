import { ModelRuntime, SettingsManager, type ExtensionAPI, type ExtensionCommandContext, type ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getSupportedThinkingLevels, type Model, type Api } from "@earendil-works/pi-ai";

// Keep credentials, model defaults and capability checks in pi itself.
export default function (pi: ExtensionAPI) {
  async function saveSelection(ctx: ExtensionContext, model: Model<Api>) {
    const settings = SettingsManager.create(ctx.cwd);
    settings.setDefaultModelAndProvider(model.provider, model.id);
    settings.setDefaultThinkingLevel(pi.getThinkingLevel());
    await settings.flush();
    if (settings.drainErrors().length) throw new Error("Selection applied to this session, but could not be saved. Please retry.");
  }

  // pi recreates its runtime on session changes and reapplies CLI defaults.
  // The last Telegram selection takes precedence, including on process restart.
  pi.on("session_start", async (_event, ctx) => {
    const saved = SettingsManager.create(ctx.cwd).getGlobalSettings();
    if (!saved.defaultProvider || !saved.defaultModel) return;
    const selected = ctx.modelRegistry.find(saved.defaultProvider, saved.defaultModel);
    try {
      if (!selected || !await pi.setModel(selected)) throw new Error("Saved model unavailable");
      if (saved.defaultThinkingLevel !== undefined) {
        if (getSupportedThinkingLevels(selected).includes(saved.defaultThinkingLevel)) {
          pi.setThinkingLevel(saved.defaultThinkingLevel);
        } else {
          ctx.ui.notify(`Saved thinking '${saved.defaultThinkingLevel}' is no longer supported by ${selected.provider}/${selected.id}. Current thinking: ${pi.getThinkingLevel()}.`, "warning");
        }
      }
    } catch {
      ctx.ui.notify(`Could not restore saved model ${saved.defaultProvider}/${saved.defaultModel}. Check /connect before continuing.`, "error");
    }
  });

  async function selectPaged(ctx: ExtensionCommandContext, title: string, options: string[]) {
    const pageSize = 6;
    let page = 0;
    while (true) {
      const choices = options.slice(page * pageSize, (page + 1) * pageSize);
      if (page > 0) choices.push("← Previous");
      if ((page + 1) * pageSize < options.length) choices.push("Next →");
      const selected = await ctx.ui.select(`${title} (${page + 1}/${Math.ceil(options.length / pageSize)})`, choices);
      if (selected === "← Previous") page--;
      else if (selected === "Next →") page++;
      else return selected;
    }
  }

  async function thinking(ctx: ExtensionCommandContext, value: string, model = ctx.model) {
    if (!model) throw new Error("Select a model first with /model.");
    const levels = getSupportedThinkingLevels(model);
    const selected = value || await ctx.ui.select(
      `Thinking: ${pi.getThinkingLevel()}`, levels,
    );
    if (selected === undefined) return;
    if (!levels.includes(selected as typeof levels[number])) {
      throw new Error(`Thinking '${selected}' is not supported by ${model.provider}/${model.id}. Allowed: ${levels.join(", ")}. Thinking unchanged.`);
    }
    pi.setThinkingLevel(selected as typeof levels[number]);
    await saveSelection(ctx, model);
    ctx.ui.notify(`Thinking: ${pi.getThinkingLevel()} (saved)`);
  }

  async function model(ctx: ExtensionCommandContext, value: string, provider?: string): Promise<Model<Api> | undefined> {
    const available = await ctx.modelRegistry.getAvailable();
    if (!available.length) throw new Error("No connected models available. Use /connect first.");
    if (!value && !provider) {
      const providers = [...new Set(available.map(m => m.provider))];
      provider = providers.length === 1 ? providers[0] : await selectPaged(ctx, "Select provider", providers);
      if (!provider) return;
    }
    const models = available.filter(m => !provider || m.provider === provider);
    if (!models.length) throw new Error(`No models available for ${provider}.`);
    const selected = value || await selectPaged(ctx, `Select model (${provider})`, models.map(m => m.id));
    if (!selected) return;
    const match = models.find(m => `${m.provider}/${m.id}` === selected ||
      (m.id === selected && (provider || m.provider === ctx.model?.provider)));
    if (!match) throw new Error("Unknown model or provider not connected. Use /connect, then /model provider/model-id.");
    const level = pi.getThinkingLevel();
    if (!await pi.setModel(match)) throw new Error("Model could not be selected. Check the provider credentials.");
    pi.setThinkingLevel(level); // Preserve the active level, clamped to the new model.
    await saveSelection(ctx, match);
    ctx.ui.notify(`Model: ${match.provider}/${match.id}. Thinking: ${pi.getThinkingLevel()} (saved)`);
    return match;
  }

  function command(name: string, description: string, handler: (args: string, ctx: ExtensionCommandContext) => Promise<unknown>) {
    pi.registerCommand(name, {
      description,
      async handler(args, ctx) {
        try {
          await handler(args.trim(), ctx);
        } catch (error) {
          // OAuth/provider errors must never include entered secrets in Telegram.
          ctx.ui.notify(name === "connect" ? "Connection/setup failed. Retry /connect or cancel with /cancel." : String(error instanceof Error ? error.message : error), "error");
        }
      },
    });
  }

  command("thinking", "Show/select thinking level, or /thinking low", async (args, ctx) => {
    await thinking(ctx, args);
  });
  command("model", "Select model: /model provider/model-id", async (args, ctx) => {
    await model(ctx, args);
  });
  command("connect", "Connect OpenRouter or an OpenAI subscription", async (args, ctx) => {
    const providers = ["openrouter", "openai-codex"];
    const provider = args || await ctx.ui.select("Connect provider (OpenAI subscription = openai-codex)", providers);
    if (!provider) return;
    if (!providers.includes(provider)) {
      ctx.ui.notify("Usage: /connect [openrouter|openai-codex]", "error");
      return;
    }
    const reuse = ctx.modelRegistry.getProviderAuthStatus(provider).configured &&
      !await ctx.ui.confirm("Provider already connected", "Replace its credentials? Choose No to keep them and select a model.");
    if (!reuse) {
      // Use pi's native login orchestration and its default persistent credential store.
      const runtime = await ModelRuntime.create({ refreshOnCreate: false });
      await runtime.login(provider, provider === "openrouter" ? "api_key" : "oauth", {
        signal: AbortSignal.timeout(5 * 60 * 1000),
        async prompt(prompt) {
          let value: string | undefined;
          if (prompt.type === "select") {
            const selected = await ctx.ui.select(prompt.message, prompt.options.map(o => o.label), { signal: prompt.signal });
            value = prompt.options.find(o => o.label === selected)?.id;
          } else {
            const title = prompt.type === "secret" ? `${prompt.message} (sent through Telegram; /cancel to cancel)` : prompt.message;
            value = await ctx.ui.input(title, prompt.placeholder, { signal: prompt.signal });
          }
          if (!value?.trim()) throw new Error("Login cancelled");
          return value.trim();
        },
        notify(event) {
          if (event.type === "auth_url") {
            ctx.ui.notify(`${event.url}\n${event.instructions ?? ""}`);
          } else if (event.type === "device_code") {
            ctx.ui.notify(`Open ${event.verificationUri}\nCode: ${event.userCode}\nLogin expires after a few minutes.`);
          } else if (event.type === "info") {
            ctx.ui.notify([event.message, ...(event.links ?? []).map(link => link.url)].join("\n"));
          }
        },
      });
    }
    await ctx.modelRegistry.refresh();
    ctx.ui.notify(`Connected: ${provider}. Select a model next.`);
    const selected = await model(ctx, "", provider);
    if (selected) await thinking(ctx, "", selected);
  });
}
