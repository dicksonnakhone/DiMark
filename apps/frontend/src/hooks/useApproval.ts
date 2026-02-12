import { useMutation, useQueryClient } from "@tanstack/react-query";
import { approveDecision } from "../lib/api";

export function useApproval(sessionId: string | null) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: ({
      decisionId,
      approved,
    }: {
      decisionId: string;
      approved: boolean;
    }) => {
      if (!sessionId) throw new Error("No session");
      return approveDecision(sessionId, decisionId, { approved });
    },
    onSuccess: (data) => {
      // Replace the cached session with the updated one
      queryClient.setQueryData(["agent-session", sessionId], data);
    },
  });

  return {
    approve: (decisionId: string) =>
      mutation.mutate({ decisionId, approved: true }),
    reject: (decisionId: string) =>
      mutation.mutate({ decisionId, approved: false }),
    isPending: mutation.isPending,
  };
}
