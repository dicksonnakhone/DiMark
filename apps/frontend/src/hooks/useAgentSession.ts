import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { continueSession, getSession, startSession } from "../lib/api";
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
    retry: (failureCount, error) => {
      // If session not found (404), don't retry
      if ((error as any)?.response?.status === 404) {
        return false;
      }
      return failureCount < 1;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // Keep polling if session is active (running, pending, or awaiting approval)
      if (
        status === "running" ||
        status === "pending" ||
        status === "awaiting_approval"
      ) {
        return 2000;
      }
      return false;
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

  // ---- Continue an existing session ----
  const continueMutation = useMutation({
    mutationFn: (message: string) =>
      continueSession(sessionId!, { message }),
    onMutate: async () => {
      if (!sessionId) return;

      queryClient.setQueryData<AgentSession | null>(
        ["agent-session", sessionId],
        (previous) => {
          if (!previous) return previous;
          return {
            ...previous,
            status: "running",
            error_message: null,
          };
        },
      );
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["agent-session", sessionId], data);
      // Re-enable polling since session is active again
      queryClient.invalidateQueries({ queryKey: ["agent-session", sessionId] });
    },
  });

  const continueConversation = useCallback(
    (message: string) => continueMutation.mutate(message),
    [continueMutation],
  );

  const clearSession = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setSessionId(null);
  }, []);

  return {
    sessionId,
    session: session ?? null,
    isStarting: startMutation.isPending,
    isContinuing: continueMutation.isPending,
    isSessionLoading,
    startError: startMutation.error,
    continueError: continueMutation.error,
    sessionError,
    start,
    continueConversation,
    clearSession,
  };
}
