import type {
  DatabaseBackend,
  ModelCatalogResponse,
  SendMessageResponse,
  SessionCreateResponse,
  SessionDetail,
  SessionMetadata,
  SessionSummary,
  StreamDoneEvent,
  StreamErrorEvent
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
  modelName?: string,
  databaseBackend?: DatabaseBackend
): Promise<SessionCreateResponse> {
  return request<SessionCreateResponse>("/sessions", {
    method: "POST",
    body: JSON.stringify({
      title,
      model_provider: modelProvider,
      model_name: modelName,
      database_backend: databaseBackend
    })
  });
}

export function fetchSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/sessions/${sessionId}`);
}

export function artifactUrl(sessionId: string, relativePath: string): string {
  return `${API_BASE_URL}/sessions/${sessionId}/artifacts/${relativePath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/")}`;
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

export async function streamMessage(
  sessionId: string,
  content: string,
  onEvent: (eventName: string, payload: unknown) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ content }),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }

  if (!response.body) {
    throw new Error("Streaming response body was not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamedDeltaEventsSinceYield = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex !== -1) {
        const rawEvent = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const eventName = _dispatchSseEvent(rawEvent, onEvent);
        if (eventName === "assistant_delta") {
          streamedDeltaEventsSinceYield += 1;
          if (streamedDeltaEventsSinceYield >= 4) {
            streamedDeltaEventsSinceYield = 0;
            await _nextAnimationFrame();
          }
        }
        separatorIndex = buffer.indexOf("\n\n");
      }

      if (done) {
        if (buffer.trim()) {
          _dispatchSseEvent(buffer, onEvent);
        }
        return;
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      await reader.cancel();
      return;
    }
    throw err;
  }
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

export function updateSessionDatabase(
  sessionId: string,
  databaseBackend: DatabaseBackend
): Promise<SessionMetadata> {
  return request<SessionMetadata>(`/sessions/${sessionId}/database`, {
    method: "PATCH",
    body: JSON.stringify({
      database_backend: databaseBackend
    })
  });
}

function _dispatchSseEvent(
  rawEvent: string,
  onEvent: (eventName: string, payload: unknown) => void
): string | null {
  const lines = rawEvent
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter(Boolean);

  if (lines.length === 0) {
    return null;
  }

  let eventName = "message";
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  const payload = JSON.parse(dataLines.join("\n")) as
    | StreamDoneEvent
    | StreamErrorEvent
    | Record<string, unknown>;
  onEvent(eventName, payload);
  return eventName;
}

function _nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}
