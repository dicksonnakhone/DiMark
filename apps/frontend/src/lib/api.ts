import axios from "axios";
import type {
  AgentSession,
  ApproveDecisionRequest,
  ContinueSessionRequest,
  StartSessionRequest,
  ToolInfo,
} from "../types";

const client = axios.create({ baseURL: "/api/agents" });

export async function startSession(
  payload: StartSessionRequest,
): Promise<AgentSession> {
  const { data } = await client.post<AgentSession>("/sessions/start", payload);
  return data;
}

export async function getSession(sessionId: string): Promise<AgentSession> {
  const { data } = await client.get<AgentSession>(`/sessions/${sessionId}`);
  return data;
}

export async function approveDecision(
  sessionId: string,
  decisionId: string,
  payload: ApproveDecisionRequest,
): Promise<AgentSession> {
  const { data } = await client.post<AgentSession>(
    `/sessions/${sessionId}/decisions/${decisionId}/approve`,
    payload,
  );
  return data;
}

export async function continueSession(
  sessionId: string,
  payload: ContinueSessionRequest,
): Promise<AgentSession> {
  const { data } = await client.post<AgentSession>(
    `/sessions/${sessionId}/continue`,
    payload,
  );
  return data;
}

export async function listTools(category?: string): Promise<ToolInfo[]> {
  const params = category ? { category } : {};
  const { data } = await client.get<ToolInfo[]>("/tools", { params });
  return data;
}
