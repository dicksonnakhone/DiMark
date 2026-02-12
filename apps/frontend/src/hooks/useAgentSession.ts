import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { getSession, startSession } from "../lib/api";
import type { AgentSession } from "../types";

const STORAGE_KEY = "current_session_id";

export function useAgentSession() {
  const queryClient = useQueryClient();

  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem(STORAGE_KEY),
  );

  // ---- Poll session while it is in a non-terminal state ----
  const {
    data: session,
    isLoading: isSessionLoading,
    error: sessionError,
  } = useQuery<AgentSession>({
    queryKey: ["agent-session", sessionId],
    queryFn: () => getSession(sessionId!),
    enabled: !!sessionId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 2000;
    },
    refetchIntervalInBackground: true,
  });

  // ---- Start a new session ----
  const startMutation = useMutation({
    mutationFn: (goal: string) => startSession({ goal }),
    onSuccess: (data) => {
      const id = data.id;
      setSessionId(id);
      localStorage.setItem(STORAGE_KEY, id);
      queryClient.setQueryData(["agent-session", id], data);
    },
  });

  const start = useCallback(
    (goal: string) => startMutation.mutate(goal),
    [startMutation],
  );

  const clearSession = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setSessionId(null);
  }, []);

  return {
    sessionId,
    session: session ?? null,
    isStarting: startMutation.isPending,
    isSessionLoading,
    startError: startMutation.error,
    sessionError,
    start,
    clearSession,
  };
}
