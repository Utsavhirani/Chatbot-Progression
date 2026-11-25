import type { ApiErrorBody, Conversation, Message, ModelSettings, ModelsResponse, User } from "./types";

/** A failed API call, carrying the backend's error envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly retryAfter: number | null;
  readonly details: Record<string, unknown> | undefined;
  readonly requestId: string | null;

  constructor(status: number, body: Partial<ApiErrorBody["error"]>, retryAfter: number | null = null) {
    super(body.message ?? `Request failed (${status})`);
    this.status = status;
    this.code = body.code ?? "http_error";
    this.retryable = body.retryable ?? false;
    this.details = body.details;
    this.requestId = body.request_id ?? null;
    this.retryAfter = retryAfter;
  }
}

export async function toApiError(resp: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody["error"]> = {};
  try {
    body = ((await resp.json()) as ApiErrorBody).error ?? {};
  } catch {
    body = { code: "http_error", message: resp.status >= 500 ? "The server is unavailable." : resp.statusText };
  }
  const retryAfter = Number(resp.headers.get("retry-after")) || null;
  return new ApiError(resp.status, body, retryAfter);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, { code: "network_error", message: "Cannot reach the server. Check your connection." });
  }
  if (!resp.ok) throw await toApiError(resp);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  me: () => request<User>("GET", "/api/auth/me"),
  register: (email: string, password: string) => request<User>("POST", "/api/auth/register", { email, password }),
  login: (email: string, password: string) => request<User>("POST", "/api/auth/login", { email, password }),
  logout: () => request<void>("POST", "/api/auth/logout"),

  models: () => request<ModelsResponse>("GET", "/api/models"),

  conversations: () => request<Conversation[]>("GET", "/api/conversations"),
  conversation: (id: string) => request<Conversation>("GET", `/api/conversations/${id}`),
  createConversation: (body: { title?: string; system_prompt?: string | null } = {}) =>
    request<Conversation>("POST", "/api/conversations", body),
  updateConversation: (
    id: string,
    body: { title?: string; system_prompt?: string | null; settings?: Partial<ModelSettings> },
  ) => request<Conversation>("PATCH", `/api/conversations/${id}`, body),
  deleteConversation: (id: string) => request<void>("DELETE", `/api/conversations/${id}`),
  messages: (id: string) => request<Message[]>("GET", `/api/conversations/${id}/messages`),
};
