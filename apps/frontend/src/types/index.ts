// ---------------------------------------------------------------------------
// Backend API types — mirrors AgentSessionOut / AgentDecisionOut / ToolOut
// ---------------------------------------------------------------------------

export interface AgentDecision {
  id: string;
  step_number: number;
  phase: "think" | "act" | "observe";
  reasoning: string | null;
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: Record<string, unknown> | null;
  requires_approval: boolean;
  approval_status: "approved" | "rejected" | null;
  created_at: string;
}

export interface AgentSession {
  id: string;
  goal: string;
  status: "pending" | "running" | "awaiting_approval" | "completed" | "failed";
  agent_type: string;
  current_step: number;
  max_steps: number;
  result_json: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  decisions: AgentDecision[];
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  parameters_schema: Record<string, unknown>;
  requires_approval: boolean;
}

// ---------------------------------------------------------------------------
// Request payloads
// ---------------------------------------------------------------------------

export interface StartSessionRequest {
  goal: string;
  agent_type?: string;
  context?: Record<string, unknown>;
  max_steps?: number;
}

export interface ApproveDecisionRequest {
  approved: boolean;
}

export interface ContinueSessionRequest {
  message: string;
}

// ---------------------------------------------------------------------------
// UI-level types for the chat view
// ---------------------------------------------------------------------------

export type MessageType = "info" | "success" | "warning" | "error";

/** A chat message derived from an AgentDecision. */
export interface ChatMessage {
  id: string;
  sender: "agent" | "user";
  agentName: string;
  text: string;
  type: MessageType;
  toolName: string | null;
  toolInput: Record<string, unknown> | null;
  toolOutput: Record<string, unknown> | null;
  requiresApproval: boolean;
  approvalStatus: "approved" | "rejected" | null;
  timestamp: string;
}
