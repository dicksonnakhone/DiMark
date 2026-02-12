import { Loader2 } from "lucide-react";

export function AgentThinking() {
  return (
    <div className="flex items-center gap-2 px-4 py-3 text-sm text-gray-500">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span>Agent is working on your request</span>
      <span className="inline-flex gap-0.5">
        <span className="animate-bounce [animation-delay:0ms]">&middot;</span>
        <span className="animate-bounce [animation-delay:150ms]">&middot;</span>
        <span className="animate-bounce [animation-delay:300ms]">&middot;</span>
      </span>
    </div>
  );
}
