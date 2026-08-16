import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ask_user",
    label: "Ask User",
    description: "Ask the user a question with answer buttons. The user may also type a different answer.",
    promptSnippet: "Ask user questions with answer buttons",
    promptGuidelines: ["Use ask_user instead of asking in assistant text. Match the user's language and include at least one likely answer."],
    parameters: Type.Object({
      question: Type.String({ description: "Question to show" }),
      options: Type.Array(Type.String(), {
        minItems: 1,
        maxItems: 8,
        description: "Answer button labels (1-8)",
      }),
      multiple: Type.Optional(Type.Boolean({ description: "Allow multiple answers" })),
      finish_label: Type.Optional(Type.String({ description: "Finish button for multiple answers" })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ctx.hasUI) {
        return { content: [{ type: "text", text: "No interactive UI available." }] };
      }

      if (!params.multiple) {
        const answer = await ctx.ui.select(params.question, params.options, {
          signal,
        });

        return {
          content: [{
            type: "text",
            text: answer === undefined ? "No answer." : `Answer: ${answer}`,
          }],
        };
      }

      const finishLabel = params.finish_label?.trim();
      if (!finishLabel || params.options.includes(finishLabel)) {
        return {
          content: [{ type: "text", text: "multiple requires a unique finish_label." }],
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
            content: [{ type: "text", text: `Answer: ${JSON.stringify(selected)}` }],
          };
        }
        selected.push(answer);
        remaining.splice(remaining.indexOf(answer), 1);
      }

      return {
        content: [{
          type: "text",
          text: "No answer.",
        }],
      };
    },
  });
}
