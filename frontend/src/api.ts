import type {
  ModelCatalogResponse,
  SendMessageResponse,
  SessionCreateResponse,
  SessionDetail,
  SessionMetadata,
  SessionSummary
} from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function fetchSessions(): Promise<SessionSummary[]> {
  return request<SessionSummary[]>("/sessions");
}

export function fetchModelCatalog(): Promise<ModelCatalogResponse> {
  return request<ModelCatalogResponse>("/models");
}

export function createSession(
  title?: string,
  modelProvider?: string,
  modelName?: string
): Promise<SessionCreateResponse> {
  return request<SessionCreateResponse>("/sessions", {
    method: "POST",
    body: JSON.stringify({
      title,
      model_provider: modelProvider,
      model_name: modelName
    })
  });
}

export function fetchSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/sessions/${sessionId}`);
}

export function updateSessionTitle(
  sessionId: string,
  title: string
): Promise<SessionMetadata> {
  return request<SessionMetadata>(`/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ title })
  });
}

export function deleteSession(sessionId: string): Promise<void> {
  return request<void>(`/sessions/${sessionId}`, {
    method: "DELETE"
  });
}

export function sendMessage(
  sessionId: string,
  content: string
): Promise<SendMessageResponse> {
  return request<SendMessageResponse>(`/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content })
  });
}

export function updateSessionModel(
  sessionId: string,
  modelProvider: string,
  modelName: string
): Promise<SessionMetadata> {
  return request<SessionMetadata>(`/sessions/${sessionId}/model`, {
    method: "PATCH",
    body: JSON.stringify({
      model_provider: modelProvider,
      model_name: modelName
    })
  });
}
