import type { ChatMessage } from "@/stores/gameStore";

/** 最近一次干涉的结果：请求之后的第一条拒绝/生效事件。 */
export function latestInterventionFeedback(
  messages: ChatMessage[]
): { status: "applied" | "rejected"; text: string } | null {
  let requestIndex = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].eventType === "intervention_requested") {
      requestIndex = i;
      break;
    }
  }
  if (requestIndex < 0) return null;
  for (let i = requestIndex + 1; i < messages.length; i += 1) {
    const message = messages[i];
    if (message.eventType === "intervention_rejected") {
      return {
        status: "rejected",
        text: message.intervention?.reason || message.text,
      };
    }
    if (
      message.eventType === "scene_created" ||
      message.eventType === "character_created" ||
      message.eventType === "pull_in_character"
    ) {
      return { status: "applied", text: message.text };
    }
  }
  return null;
}
