import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ask_user",
    label: "Ask User",
    description: "Ask the user a question with one to eight short, freely chosen answer buttons. Choose the button labels dynamically in the same language and tone as the conversation. Use only a few relevant options; the user may still type a different answer.",
    promptSnippet: "Ask focused follow-up questions with dynamic answer buttons",
    promptGuidelines: [
      "Use ask_user when a question has a small set of likely answers.",
      "Write the question and every option in the same language and tone used with the user.",
      "Choose all labels dynamically. Do not add generic confirmation or cancellation choices unless they are useful in context.",
      "For multiple choice, provide a short finish_label in the user's language and tone.",
    ],
    parameters: Type.Object({
      question: Type.String({ description: "Question shown to the user" }),
      options: Type.Array(Type.String({ description: "Short answer button label" }), {
        minItems: 1,
        maxItems: 8,
        description: "One to eight likely answers, written in the user's language",
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
