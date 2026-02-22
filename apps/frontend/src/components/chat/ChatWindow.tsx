import { AlertCircle, Plus, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAgentSession } from "../../hooks/useAgentSession";
import { decisionsToMessages } from "../../lib/utils";
import type { ChatMessage } from "../../types";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { AgentThinking } from "./AgentThinking";
import { MessageInput } from "./MessageInput";
import { MessageList } from "./MessageList";

// ---------------------------------------------------------------------------
// Example goals for the landing screen
// ---------------------------------------------------------------------------

const EXAMPLES = [
  "Generate 100 qualified leads for my B2B SaaS in 30 days",
  "Launch new product with brand awareness campaign, $5k budget",
  "Get 50 sign-ups for my AI writing tool in 2 weeks",
];

const USER_MESSAGES_STORAGE_PREFIX = "chat_user_messages";

function getUserMessageStorageKey(sessionId: string): string {
  return `${USER_MESSAGES_STORAGE_PREFIX}:${sessionId}`;
}

function buildUserMessage(text: string): ChatMessage {
  return {
    id: `user-${crypto.randomUUID()}`,
    sender: "user",
    agentName: "You",
    text,
    type: "info",
    toolName: null,
    toolInput: null,
    toolOutput: null,
    requiresApproval: false,
    approvalStatus: null,
    timestamp: new Date().toISOString(),
  };
}

function parseTimestamp(value: string): number {
  const ts = Date.parse(value);
  return Number.isNaN(ts) ? Number.MAX_SAFE_INTEGER : ts;
}

function getFinalAnswerText(value: unknown): string {
  if (typeof value === "string" && value.trim().length > 0) return value;
  if (value == null) return "The agent has finished working on your goal.";
  try {
    return JSON.stringify(value);
  } catch {
    return "The agent has finished working on your goal.";
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChatWindow() {
  const {
    sessionId,
    session,
    isStarting,
    isContinuing,
    isSessionLoading,
    sessionError,
    startError,
    continueError,
    start,
    continueConversation,
    clearSession,
  } = useAgentSession();

  const [goalDraft, setGoalDraft] = useState("");
  const [userMessages, setUserMessages] = useState<ChatMessage[]>([]);

  useEffect(() => {
    if (!sessionId) {
      setUserMessages([]);
      return;
    }

    const raw = localStorage.getItem(getUserMessageStorageKey(sessionId));
    if (!raw) {
      setUserMessages([]);
      return;
    }

    try {
      const parsed = JSON.parse(raw) as ChatMessage[];
      setUserMessages(Array.isArray(parsed) ? parsed : []);
    } catch {
      setUserMessages([]);
    }
  }, [sessionId]);

  const handleStart = useCallback(() => {
    const trimmed = goalDraft.trim();
    if (!trimmed) return;
    start(trimmed);
    setGoalDraft("");
  }, [goalDraft, start]);

  const agentMessages = session ? decisionsToMessages(session.decisions) : [];
  const messages = useMemo(() => {
    return [...userMessages, ...agentMessages].sort((a, b) => {
      const delta = parseTimestamp(a.timestamp) - parseTimestamp(b.timestamp);
      if (delta !== 0) return delta;
      if (a.sender === b.sender) return 0;
      return a.sender === "user" ? -1 : 1;
    });
  }, [agentMessages, userMessages]);
  const isActive =
    session?.status === "running" || session?.status === "pending";
  const canContinue =
    session?.status === "completed" || session?.status === "failed";
  const isProcessing = isActive || isContinuing;

  // ---------- Landing screen (no active session) ----------

  if (!sessionId) {
    return (
      <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-4">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-100">
            <Sparkles className="h-7 w-7 text-blue-600" />
          </div>
          <h1 className="mb-2 text-2xl font-bold text-gray-900">
            Marketing AI Assistant
          </h1>
          <p className="text-gray-500">
            Tell me what you want to achieve, and I'll create a data-driven
            strategy.
          </p>
        </div>

        <div className="w-full">
          <textarea
            value={goalDraft}
            onChange={(e) => setGoalDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleStart();
              }
            }}
            placeholder="What are you trying to achieve?"
            rows={3}
            className="w-full resize-none rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm shadow-sm outline-none placeholder:text-gray-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-200"
          />

          <Button
            onClick={handleStart}
            disabled={isStarting || !goalDraft.trim()}
            className="mt-3 w-full"
          >
            {isStarting ? "Starting..." : "Start Campaign"}
          </Button>

          {startError && (
            <p className="mt-2 flex items-center gap-1 text-sm text-red-600">
              <AlertCircle className="h-4 w-4" />
              {(startError as Error).message ?? "Failed to start session"}
            </p>
          )}
        </div>

        <div className="mt-8 w-full">
          <p className="mb-3 text-xs font-medium uppercase tracking-wide text-gray-400">
            Try these examples
          </p>
          <div className="space-y-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => setGoalDraft(ex)}
                className="w-full rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-left text-sm text-gray-600 transition-colors hover:border-blue-300 hover:bg-blue-50"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ---------- Loading session for the first time ----------

  if (isSessionLoading && !session) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-gray-500">Loading session...</p>
      </div>
    );
  }

  // ---------- Chat interface ----------

  const handleContinue = (message: string) => {
    const trimmed = message.trim();
    if (!trimmed || !sessionId) return;

    const userMessage = buildUserMessage(trimmed);
    setUserMessages((prev) => {
      const next = [...prev, userMessage];
      localStorage.setItem(getUserMessageStorageKey(sessionId), JSON.stringify(next));
      return next;
    });

    continueConversation(trimmed);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-gray-800">
            Campaign Planning
          </h2>
          {session && <Badge variant={session.status}>{session.status}</Badge>}
        </div>
        <Button variant="ghost" onClick={clearSession} title="New session">
          <Plus className="h-4 w-4" />
          New
        </Button>
      </header>

      {/* Messages */}
      {session && (
        <MessageList
          messages={messages}
          sessionId={session.id}
          userGoal={session.goal}
        />
      )}

      {/* Thinking indicator */}
      {isActive && <AgentThinking />}

      {/* Error banner */}
      {session?.status === "failed" && (
        <div className="flex items-center gap-2 bg-red-50 px-4 py-2 text-sm text-red-700">
          <AlertCircle className="h-4 w-4" />
          {session.error_message ?? "Session failed unexpectedly."}
        </div>
      )}

      {/* Completed banner */}
      {session?.status === "completed" && session.result_json && (
        <div className="border-t border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          <p className="font-medium">Session complete</p>
          <p className="mt-1 text-green-700">
            {getFinalAnswerText(
              (session.result_json as Record<string, unknown>)["final_answer"],
            )}
          </p>
        </div>
      )}

      {/* Input */}
      <MessageInput
        onSend={handleContinue}
        disabled={!canContinue || isProcessing}
        placeholder={
          isProcessing
            ? "Agent is working..."
            : session?.status === "awaiting_approval"
              ? "Respond to the approval request above"
              : canContinue
                ? "Send a message to continue the conversation..."
                : "Session ended — start a new one"
        }
      />

      {/* Continue error */}
      {continueError && (
        <div className="flex items-center gap-2 bg-red-50 px-4 py-2 text-sm text-red-700">
          <AlertCircle className="h-4 w-4" />
          {(continueError as Error).message ?? "Failed to continue session"}
        </div>
      )}

      {/* Session refresh error */}
      {sessionError && (
        <div className="flex items-center gap-2 bg-red-50 px-4 py-2 text-sm text-red-700">
          <AlertCircle className="h-4 w-4" />
          {(sessionError as Error).message ?? "Failed to refresh session"}
        </div>
      )}
    </div>
  );
}
