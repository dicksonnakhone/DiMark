import { BarChart3, MessageSquare, Rocket, Target, Wrench } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "../../lib/utils";
import type { ChatMessage } from "../../types";
import { ApprovalCard } from "./ApprovalCard";

// ---------------------------------------------------------------------------
// Agent visual config
// ---------------------------------------------------------------------------

const agentConfig: Record<
  string,
  { icon: React.ElementType; color: string; border: string; bg: string }
> = {
  Orchestrator: {
    icon: MessageSquare,
    color: "text-gray-600",
    border: "border-l-gray-300",
    bg: "bg-gray-50",
  },
  "Planner Agent": {
    icon: Target,
    color: "text-blue-600",
    border: "border-l-blue-300",
    bg: "bg-blue-50",
  },
  "Executor Agent": {
    icon: Rocket,
    color: "text-green-600",
    border: "border-l-green-300",
    bg: "bg-green-50",
  },
  "Analyzer Agent": {
    icon: BarChart3,
    color: "text-purple-600",
    border: "border-l-purple-300",
    bg: "bg-purple-50",
  },
};

const defaultAgent = {
  icon: Wrench,
  color: "text-gray-600",
  border: "border-l-gray-300",
  bg: "bg-gray-50",
};

// Map message type to overrides
const typeStyles: Record<string, { border: string; bg: string }> = {
  success: { border: "border-l-green-400", bg: "bg-green-50" },
  warning: { border: "border-l-amber-400", bg: "bg-amber-50" },
  error: { border: "border-l-red-400", bg: "bg-red-50" },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface AgentMessageProps {
  message: ChatMessage;
  sessionId: string;
}

export function AgentMessage({ message, sessionId }: AgentMessageProps) {
  const config = agentConfig[message.agentName] ?? defaultAgent;
  const Icon = config.icon;

  const isThought = message.text.startsWith("\u{1F4AD}"); // starts with 💭
  const isToolUse =
    message.toolName !== null && message.text.startsWith("Used tool");

  // Use type-specific styles if they exist, otherwise fall back to agent
  const typeOverride = typeStyles[message.type];
  const borderClass = typeOverride?.border ?? config.border;
  const bgClass = typeOverride?.bg ?? config.bg;

  return (
    <div className="flex gap-3">
      {/* Agent icon */}
      <div
        className={cn(
          "mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          bgClass,
        )}
      >
        <Icon className={cn("h-4 w-4", config.color)} />
      </div>

      {/* Message body */}
      <div className="min-w-0 flex-1">
        <div className="mb-0.5 flex items-center gap-2">
          <span className={cn("text-xs font-semibold", config.color)}>
            {message.agentName}
          </span>
          <span className="text-xs text-gray-400">
            {formatDistanceToNow(new Date(message.timestamp), {
              addSuffix: true,
            })}
          </span>
        </div>

        <div
          className={cn(
            "rounded-lg border-l-4 px-3 py-2 text-sm text-gray-700",
            borderClass,
            bgClass,
            isThought && "italic opacity-80",
            isToolUse && "font-mono text-xs",
          )}
        >
          <p className="whitespace-pre-wrap">{message.text}</p>

          {/* Collapsed tool I/O */}
          {isToolUse && message.toolOutput && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-700">
                Show tool output
              </summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-white/60 p-2 text-xs">
                {JSON.stringify(message.toolOutput, null, 2)}
              </pre>
            </details>
          )}
        </div>

        {/* Approval card */}
        {message.requiresApproval && (
          <ApprovalCard message={message} sessionId={sessionId} />
        )}
      </div>
    </div>
  );
}
