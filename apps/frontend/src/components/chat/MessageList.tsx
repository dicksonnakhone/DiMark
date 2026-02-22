import { memo, useEffect, useRef } from "react";
import type { ChatMessage } from "../../types";
import { AgentMessage } from "./AgentMessage";

interface MessageListProps {
  messages: ChatMessage[];
  sessionId: string;
  userGoal: string;
}

const MemoizedAgentMessage = memo(AgentMessage);

export function MessageList({
  messages,
  sessionId,
  userGoal,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
      {/* User's original goal as first message */}
      <div className="flex justify-end">
        <div className="max-w-sm rounded-lg bg-blue-600 px-4 py-3 text-sm text-white shadow-sm">
          {userGoal}
        </div>
      </div>

      {/* Agent messages */}
      {messages.map((msg) => (
        msg.sender === "user" ? (
          <div key={msg.id} className="flex justify-end">
            <div className="max-w-sm rounded-lg bg-blue-600 px-4 py-3 text-sm text-white shadow-sm">
              {msg.text}
            </div>
          </div>
        ) : (
          <MemoizedAgentMessage
            key={msg.id}
            message={msg}
            sessionId={sessionId}
          />
        )
      ))}

      {messages.length === 0 && (
        <p className="text-center text-sm text-gray-400">
          The agent will start working on your goal shortly.
        </p>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
