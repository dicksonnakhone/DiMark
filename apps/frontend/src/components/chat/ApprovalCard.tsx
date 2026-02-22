import { Check, X } from "lucide-react";
import { useApproval } from "../../hooks/useApproval";
import { cn } from "../../lib/utils";
import type { ChatMessage } from "../../types";
import { Button } from "../ui/button";
import { Card } from "../ui/card";

interface ApprovalCardProps {
  message: ChatMessage;
  sessionId: string;
}

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "[unserializable payload]";
  }
}

export function ApprovalCard({ message, sessionId }: ApprovalCardProps) {
  const { approve, reject, isPending } = useApproval(sessionId);

  const resolved = message.approvalStatus !== null;
  const wasApproved = message.approvalStatus === "approved";

  const toolOutput = (message.toolOutput ?? {}) as Record<string, unknown>;
  const action =
    (toolOutput["action"] as string) ??
    message.toolName ??
    "Pending action";
  const details = toolOutput["details"];
  const hasDetails =
    typeof details === "object" &&
    details !== null &&
    Object.keys(details).length > 0;

  return (
    <Card
      className={cn(
        "mt-2 border-l-4",
        resolved
          ? wasApproved
            ? "border-l-green-400 bg-green-50/50"
            : "border-l-red-400 bg-red-50/50"
          : "border-l-amber-400 bg-amber-50/50",
      )}
    >
      <p className="mb-1 text-sm font-semibold text-gray-700">
        Approval Required
      </p>
      <p className="mb-2 text-sm text-gray-600">{action}</p>

      {hasDetails && (
        <pre className="mb-3 max-h-40 overflow-auto rounded bg-gray-100 p-2 text-xs text-gray-700">
          {safeJson(details)}
        </pre>
      )}

      {resolved ? (
        <p
          className={cn(
            "text-xs font-medium",
            wasApproved ? "text-green-700" : "text-red-700",
          )}
        >
          {wasApproved ? "Approved" : "Rejected"}
        </p>
      ) : (
        <div className="flex gap-2">
          <Button
            variant="success"
            disabled={isPending}
            onClick={() => approve(message.id)}
          >
            <Check className="h-4 w-4" />
            Approve
          </Button>
          <Button
            variant="danger"
            disabled={isPending}
            onClick={() => reject(message.id)}
          >
            <X className="h-4 w-4" />
            Reject
          </Button>
        </div>
      )}
    </Card>
  );
}
