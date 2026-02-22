import type { AgentDecision, ChatMessage, MessageType } from "../types";

/**
 * Derive the visual message type from a decision's phase and tool output.
 */
function inferMessageType(d: AgentDecision): MessageType {
  if (d.phase === "act" && d.tool_output) {
    const out = d.tool_output as Record<string, unknown>;
    if (out["error"]) return "error";
    if (out["approval_requested"]) return "warning";
  }
  if (d.phase === "think") return "info";
  return "info";
}

/**
 * Build a user-readable text from a decision.
 */
function buildText(d: AgentDecision): string {
  if (typeof d.reasoning === "string" && d.reasoning.length > 0) {
    return d.reasoning;
  }
  if (d.phase === "act" && d.tool_name) {
    if (d.tool_output) {
      const out = d.tool_output as Record<string, unknown>;
      // Chat tool output
      if (typeof out["message"] === "string") return out["message"] as string;
      return `Used tool **${d.tool_name}**`;
    }
    return `Calling tool: ${d.tool_name}...`;
  }
  if (d.phase === "observe") return "Reviewing results...";
  return "";
}

/**
 * Convert backend AgentDecision[] into an ordered list of ChatMessages
 * suitable for the UI. Skips observe-phase decisions (internal plumbing).
 */
export function decisionsToMessages(decisions: AgentDecision[]): ChatMessage[] {
  return decisions
    .filter((d) => d.phase !== "observe" && buildText(d).length > 0)
    .map((d) => ({
      id: d.id,
      sender: "agent" as const,
      agentName: d.tool_name ? "Planner Agent" : "Planner Agent",
      text: buildText(d),
      type: inferMessageType(d),
      toolName: d.tool_name,
      toolInput: d.tool_input,
      toolOutput: d.tool_output,
      requiresApproval: d.requires_approval,
      approvalStatus: d.approval_status,
      timestamp:
        typeof d.created_at === "string"
          ? d.created_at
          : new Date().toISOString(),
    }));
}

/**
 * Merge class names (minimal clsx replacement).
 */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
