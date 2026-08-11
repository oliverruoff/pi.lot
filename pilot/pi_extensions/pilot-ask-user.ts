import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ask_user",
    label: "Ask User",
    description: "Use this tool for every question addressed to the user. Never ask the user a question only in normal assistant text. Always provide at least one short, useful answer button; for confirmations, include the obvious affirmative action (for example, 'Yes, do it!'). Choose labels dynamically in the same language and tone as the conversation. The user may still type a different answer.",
    promptSnippet: "Always ask the user through ask_user and provide at least one useful answer button",
    promptGuidelines: [
      "Use ask_user for every question addressed to the user, including clarifications, confirmations, permission requests, preferences, and open-ended questions.",
      "Never end or continue an assistant message with a textual question for the user. Call ask_user instead.",
      "Always offer at least one useful, likely answer. For a yes/no or action confirmation, include an affirmative option that names the action, such as 'Yes, do it!'.",
      "Write the question and every option in the same language and tone used with the user.",
      "Choose concise, self-contained labels dynamically. Add only options that make answering easier; the user can always type a different response.",
      "For multiple choice, provide a short finish_label in the user's language and tone.",
    ],
    parameters: Type.Object({
      question: Type.String({ description: "Question shown to the user" }),
      options: Type.Array(Type.String({ description: "Short answer button label" }), {
        minItems: 1,
        maxItems: 8,
        description: "Required: one to eight useful likely answers, written in the user's language. For confirmations, include the affirmative action.",
      }),
      multiple: Type.Optional(Type.Boolean({ description: "Allow the user to choose several options" })),
      finish_label: Type.Optional(Type.String({ description: "Model-chosen button label that completes a multiple choice, required when multiple is true" })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ctx.hasUI) {
        return { content: [{ type: "text", text: "No interactive user interface is available." }] };
      }

      if (!params.multiple) {
        const answer = await ctx.ui.select(params.question, params.options, {
          signal,
        });

        return {
          content: [{
            type: "text",
            text: answer === undefined ? "The user did not provide an answer." : `User answered: ${answer}`,
          }],
        };
      }

      const finishLabel = params.finish_label?.trim();
      if (!finishLabel || params.options.includes(finishLabel)) {
        return {
          content: [{ type: "text", text: "multiple choice requires a unique finish_label." }],
          isError: true,
        };
      }

      const remaining = [...params.options];
      const selected: string[] = [];

      while (true) {
        const answer = await ctx.ui.select(params.question, [...remaining, finishLabel], {
          signal,
        });
        if (answer === undefined) break;
        if (answer === finishLabel) {
          return {
            content: [{ type: "text", text: `User answered: ${JSON.stringify(selected)}` }],
          };
        }
        selected.push(answer);
        remaining.splice(remaining.indexOf(answer), 1);
      }

      return {
        content: [{
          type: "text",
          text: "The user did not provide an answer.",
        }],
      };
    },
  });
}
