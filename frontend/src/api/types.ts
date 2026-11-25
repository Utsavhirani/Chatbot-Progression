// Mirrors backend schemas (backend/app/schemas/*). Keep in sync when the API changes.

export type User = { id: string; email: string; created_at: string };

export type ModelSettings = { model: string; temperature: number; max_tokens: number };

export type Conversation = {
  id: string;
  title: string;
  system_prompt: string | null;
  settings: ModelSettings;
  created_at: string;
  updated_at: string;
};

export type MessageStatus = "complete" | "streaming" | "partial" | "failed" | "cancelled";

export type Message = {
  id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  error_code: string | null;
  client_message_id: string | null;
  reply_to_id: string | null;
  created_at: string;
};

export type ModelInfo = {
  id: string;
  display_name: string;
  max_output_tokens: number;
  default_max_tokens: number;
  reasoning: boolean;
};

export type ModelsResponse = { default_model: string; models: ModelInfo[] };

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    request_id: string | null;
    details?: Record<string, unknown>;
  };
};

// --- SSE events from POST /messages and /retry ---------------------------------
export type StreamErrorData = {
  code: string;
  message: string;
  retryable: boolean;
  retry_after: number | null;
  id?: string;
  status?: MessageStatus;
};

export type StreamEvent =
  | { event: "user_message"; data: { id: string; seq: number; client_message_id: string } }
  | { event: "assistant_started"; data: { id: string; seq: number; model: string } }
  | { event: "delta"; data: { text: string } }
  | { event: "usage"; data: Record<string, number | null> }
  | { event: "done"; data: { id: string; status: "complete"; finish_reason: string | null } }
  | { event: "error"; data: StreamErrorData };
