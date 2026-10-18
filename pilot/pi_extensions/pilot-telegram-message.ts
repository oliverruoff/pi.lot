import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { randomUUID } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

async function contacts(): Promise<Record<string, { chat_id?: number }>> {
  const file = process.env.PILOT_TELEGRAM_CONTACTS;
  if (!file) throw new Error("PILOT_TELEGRAM_CONTACTS is not set");
  try {
    return JSON.parse(await fs.readFile(file, "utf8"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw error;
  }
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "list_telegram_contacts",
    label: "List Telegram Contacts",
    description: "List registered Telegram recipients by name. Only the main user can invite recipients with /adduser <name>.",
    parameters: Type.Object({}),
    async execute() {
      const names = Object.entries(await contacts())
        .filter(([, entry]) => entry.chat_id !== undefined)
        .map(([name]) => name);
      return { content: [{ type: "text", text: JSON.stringify(names) }] };
    },
  });

  pi.registerTool({
    name: "send_telegram_message",
    label: "Send Telegram Message",
    description: "Queue a plain text message to a registered Telegram recipient. Use only when the main user asks to send a message, including scheduled messages. Queued does not mean delivered; delivery errors are reported to the main user.",
    parameters: Type.Object({
      recipient: Type.String({ description: "Exact name from list_telegram_contacts" }),
      text: Type.String({ minLength: 1, maxLength: 4096, description: "Message to send" }),
    }),
    async execute(_toolCallId, params) {
      const outbox = process.env.PILOT_TELEGRAM_FILE_OUTBOX;
      if (!outbox) throw new Error("PILOT_TELEGRAM_FILE_OUTBOX is not set");
      const chatId = (await contacts())[params.recipient]?.chat_id;
      if (chatId === undefined) throw new Error(`Contact is not registered: ${params.recipient}`);
      await fs.mkdir(outbox, { recursive: true });
      const id = `${Date.now()}-${randomUUID()}`;
      const temporary = path.join(outbox, `${id}.tmp`);
      await fs.writeFile(temporary, JSON.stringify({ recipient: params.recipient, chat_id: chatId, text: params.text }) + "\n", "utf8");
      await fs.rename(temporary, path.join(outbox, `${id}.json`));
      return { content: [{ type: "text", text: `Message to ${params.recipient} queued for Telegram delivery.` }] };
    },
  });
}
