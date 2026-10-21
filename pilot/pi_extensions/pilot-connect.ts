import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { getSupportedThinkingLevels, type Model, type Api } from "@earendil-works/pi-ai";

// Keep credentials, model defaults and capability checks in pi itself.
export default function (pi: ExtensionAPI) {
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
    ctx.ui.notify(`Thinking: ${pi.getThinkingLevel()}`);
  }

  async function model(ctx: ExtensionCommandContext, value: string, provider?: string): Promise<Model<Api> | undefined> {
    const models = (await ctx.modelRegistry.getAvailable()).filter(m => !provider || m.provider === provider);
    const selected = value || await ctx.ui.input(
      `Model${provider ? ` (${provider})` : " (provider/model-id)"}. Current: ${ctx.model?.id ?? "none"}`,
      models.slice(0, 3).map(m => provider ? m.id : `${m.provider}/${m.id}`).join(", "),
    );
    if (!selected) return;
    const match = models.find(m => `${m.provider}/${m.id}` === selected ||
      (m.id === selected && (provider || m.provider === ctx.model?.provider)));
    if (!match) throw new Error("Unknown model or provider not connected. Use /connect, then /model provider/model-id.");
    if (!await pi.setModel(match)) throw new Error("Model could not be selected. Check the provider credentials.");
    ctx.ui.notify(`Model: ${match.provider}/${match.id}. Thinking: ${pi.getThinkingLevel()}`);
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
    const auth = ctx.modelRegistry.authStorage;
    if (ctx.modelRegistry.getProviderAuthStatus(provider).configured &&
        !await ctx.ui.confirm("Provider already connected", "Replace its credentials? Choose No to keep them and select a model.")) {
      // Existing env or stored credentials can be used without entering them again.
    } else if (provider === "openrouter") {
      const key = await ctx.ui.input("OpenRouter API key (sent through Telegram; /cancel to cancel)");
      if (!key?.trim()) return;
      auth.set(provider, { type: "api_key", key: key.trim() });
    } else {
      const input = async (title: string) => {
        const value = await ctx.ui.input(title);
        if (!value) throw new Error("Login cancelled");
        return value;
      };
      await auth.login(provider, {
        signal: AbortSignal.timeout(5 * 60 * 1000),
        onAuth: info => ctx.ui.notify(`${info.url}\n${info.instructions ?? ""}`),
        onDeviceCode: info => ctx.ui.notify(`Open ${info.verificationUri}\nCode: ${info.userCode}\nLogin expires after a few minutes.`),
        onPrompt: prompt => input(prompt.message),
        onManualCodeInput: () => input("Paste the complete callback URL from your browser (/cancel to cancel)"),
        onSelect: async prompt => {
          const selected = await ctx.ui.select(prompt.message, prompt.options.map(o => o.label));
          return prompt.options.find(o => o.label === selected)?.id;
        },
      });
    }
    ctx.modelRegistry.refresh();
    ctx.ui.notify(`Connected: ${provider}. Select a model next.`);
    const selected = await model(ctx, "", provider);
    if (selected) await thinking(ctx, "", selected);
  });
}
