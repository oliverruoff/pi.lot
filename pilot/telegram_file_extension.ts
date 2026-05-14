import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "send_telegram_file",
    label: "Send Telegram File",
    description: "Send a local file from this pi.lot machine to the authorized Telegram chat. Use only when the user explicitly asks to receive a local file.",
    promptSnippet: "Send local files to the authorized Telegram chat",
    promptGuidelines: ["Use send_telegram_file only when the user explicitly asks to receive a local file via Telegram."],
    parameters: Type.Object({
      path: Type.String({ description: "Local file path to send" }),
      caption: Type.Optional(Type.String({ description: "Optional Telegram caption" })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const outbox = process.env.PILOT_TELEGRAM_FILE_OUTBOX;
      if (!outbox) throw new Error("PILOT_TELEGRAM_FILE_OUTBOX is not set");
      const filePath = path.resolve(ctx.cwd, params.path);
      const stat = await fs.stat(filePath);
      if (!stat.isFile()) throw new Error(`${filePath} is not a file`);
      await fs.mkdir(outbox, { recursive: true });
      const id = `${Date.now()}-${randomUUID()}`;
      const tmp = path.join(outbox, `${id}.tmp`);
      const dest = path.join(outbox, `${id}.json`);
      await fs.writeFile(tmp, JSON.stringify({ path: filePath, caption: params.caption || "" }) + "\n", "utf8");
      await fs.rename(tmp, dest);
      return { content: [{ type: "text", text: `Queued ${filePath} to be sent via Telegram.` }] };
    },
  });
}
