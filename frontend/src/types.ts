export type Role = "user" | "assistant" | "system";
export type ModelProvider = "openai" | "anthropic";

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  created_at: string;
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  model_provider: ModelProvider;
  model_name: string;
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
