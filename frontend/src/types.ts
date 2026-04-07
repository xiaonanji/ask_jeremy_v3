export type Role = "user" | "assistant" | "system";
export type ModelProvider = "openai" | "anthropic";
export type DatabaseBackend = "sqlite" | "snowflake";

export interface ChatArtifact {
  filename: string;
  relative_path: string;
  mime_type?: string | null;
  size_bytes: number;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  created_at: string;
  artifacts: ChatArtifact[];
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  model_provider: ModelProvider;
  model_name: string;
  database_backend: DatabaseBackend;
}

export interface SessionMetadata extends SessionSummary {
  workspace_path: string;
}

export interface SessionDetail {
  session: SessionMetadata;
  messages: ChatMessage[];
}

export interface SessionCreateResponse {
  session: SessionMetadata;
  messages: ChatMessage[];
}

export interface SendMessageResponse {
  session: SessionMetadata;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export interface StreamDoneEvent {
  session: SessionMetadata;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export interface StreamErrorEvent {
  message: string;
}

export interface ModelCatalogEntry {
  provider: ModelProvider;
  model_name: string;
  label: string;
}

export interface ModelCatalogResponse {
  default_provider: ModelProvider;
  default_model_name: string;
  models: ModelCatalogEntry[];
}
