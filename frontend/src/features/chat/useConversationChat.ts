import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import { StreamInterruptedError, postSSE } from "../../api/sse";
import type { Message, MessageStatus, StreamEvent } from "../../api/types";
import { conversationKey, conversationsKey } from "../conversations/queries";

export type UiError = { code: string; message: string; retryable: boolean; retryAfter?: number | null };

export type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  error?: UiError;
  /** Informational note on a complete reply (e.g. cut off by the length limit). */
  note?: string;
};

const LENGTH_NOTE = "This reply reached the maximum length. Increase it in the conversation settings.";

export const messagesKey = (id: string) => ["messages", id] as const;

// Text for error codes stored on messages. Kept identical to the live SSE error messages
// (backend app/chat/service.py _PUBLIC_ERRORS) so the text does not change after re-syncing.
const STORED_ERROR_TEXT: Record<string, string> = {
  provider_rate_limited: "The AI service is busy right now (rate limit). Please try again shortly.",
  provider_unavailable: "The AI service is temporarily unavailable. Please try again.",
  provider_timeout: "The AI service took too long to respond. Please try again.",
  provider_stream_interrupted: "The response was interrupted. You can retry it.",
  provider_bad_response: "The AI service returned an unexpected response. Please try again.",
  provider_bad_request: "The AI service could not process this request.",
  provider_auth: "The AI service is not configured correctly. Please contact support.",
  request_too_large: "This request is larger than the AI service currently allows. Shorten it.",
  context_too_large: "This conversation is too long for the selected model.",
  client_disconnected: "The response was stopped.",
  connection_lost: "Connection to the server was lost while the reply was being generated.",
  server_restarted: "The server restarted while replying. You can retry it.",
  abandoned: "The reply did not finish. You can retry it.",
};

function fromServer(m: Message): UiMessage {
  const failed = m.status === "failed" || m.status === "partial" || m.status === "cancelled";
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    status: m.status,
    error: failed
      ? {
          code: m.error_code ?? "failed",
          message: STORED_ERROR_TEXT[m.error_code ?? ""] ?? "The reply did not complete.",
          retryable: true,
        }
      : undefined,
    note: m.status === "complete" && m.error_code === "length_limit" ? LENGTH_NOTE : undefined,
  };
}

/** Message for a request the server rejected before streaming started. */
export function describeRejection(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "rate_limited" && err.retryAfter) return `${err.message} (try again in ${err.retryAfter}s)`;
    return err.message;
  }
  return "Something went wrong. Please try again.";
}

/**
 * Local message state for one conversation, kept in sync with the server.
 * The server stays the source of truth: after every stream the history is re-fetched.
 */
export function useConversationChat(conversationId: string | undefined) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: messagesKey(conversationId ?? "none"),
    queryFn: () => api.messages(conversationId!),
    enabled: !!conversationId,
    // A reply can still show as "streaming" briefly after a cancel; poll until the server settles it.
    refetchInterval: (q) => (q.state.data?.some((m) => m.status === "streaming") ? 1000 : false),
  });

  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const runningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (query.data && !runningRef.current) setMessages(query.data.map(fromServer));
  }, [query.data]);

  // Navigating away does NOT abort an in-flight reply: the request keeps running, the server
  // finishes and stores the reply, and coming back shows it. Only the Stop button cancels.
  // (Aborting on unmount could drop a just-sent message before it ever reached the server.)

  // A reply still generating on the server that this view did not start (e.g. after navigating
  // away and back): sending is disabled until it settles (the query polls meanwhile).
  const serverBusy = !!query.data?.some((m) => m.status === "streaming") && !isRunning;

  const patch = (id: string, fn: (m: UiMessage) => UiMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  /** Run one SSE generation. Returns the rejection error if the server refused before streaming. */
  const stream = useCallback(
    async (path: string, body: unknown, assistantId: string, userTempId: string | null) => {
      if (!conversationId) return null;
      runningRef.current = true;
      setIsRunning(true);
      setNotice(null);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      let current = assistantId;
      let rejection: unknown = null;

      const onEvent = (ev: StreamEvent) => {
        switch (ev.event) {
          case "user_message":
            if (userTempId) patch(userTempId, (m) => ({ ...m, id: ev.data.id }));
            break;
          case "assistant_started": {
            const prev = current;
            current = ev.data.id;
            patch(prev, (m) => ({ ...m, id: ev.data.id, status: "streaming", content: "", error: undefined }));
            break;
          }
          case "delta":
            patch(current, (m) => ({ ...m, content: m.content + ev.data.text }));
            break;
          case "done":
            patch(current, (m) => ({
              ...m,
              status: "complete",
              note: ev.data.finish_reason === "length" ? LENGTH_NOTE : undefined,
            }));
            break;
          case "error":
            patch(current, (m) => ({
              ...m,
              status: ev.data.status ?? "failed",
              error: {
                code: ev.data.code,
                message: ev.data.message,
                retryable: ev.data.retryable,
                retryAfter: ev.data.retry_after,
              },
            }));
            break;
        }
      };

      try {
        await postSSE(path, body, onEvent, ctrl.signal);
      } catch (err) {
        if (ctrl.signal.aborted) {
          patch(current, (m) => ({
            ...m,
            status: "cancelled",
            error: { code: "client_disconnected", message: STORED_ERROR_TEXT.client_disconnected, retryable: true },
          }));
        } else if (err instanceof StreamInterruptedError) {
          patch(current, (m) => ({
            ...m,
            status: m.content ? "partial" : "failed",
            error: { code: "connection_lost", message: err.message, retryable: true },
          }));
        } else {
          // Rejected before streaming (validation, duplicate, rate limit, conflict, session expired, ...).
          rejection = err;
          if (userTempId) setMessages((ms) => ms.filter((m) => m.id !== userTempId && m.id !== current));
          setNotice(describeRejection(err));
          if (err instanceof ApiError && err.code === "unauthenticated") qc.invalidateQueries({ queryKey: ["me"] });
        }
      } finally {
        runningRef.current = false;
        setIsRunning(false);
        abortRef.current = null;
        // Re-sync with the server's record (ids, final statuses, auto-title, ordering).
        void qc.invalidateQueries({ queryKey: messagesKey(conversationId) });
        void qc.invalidateQueries({ queryKey: conversationsKey });
        void qc.invalidateQueries({ queryKey: conversationKey(conversationId) }); // auto-title
      }
      return rejection;
    },
    [conversationId, qc],
  );

  const send = useCallback(
    async (text: string) => {
      if (!conversationId || runningRef.current) return null;
      const clientId = crypto.randomUUID();
      const userTemp = `local-user-${clientId}`;
      const assistantTemp = `local-assistant-${clientId}`;
      setMessages((ms) => [
        ...ms,
        { id: userTemp, role: "user", content: text, status: "complete" },
        { id: assistantTemp, role: "assistant", content: "", status: "streaming" },
      ]);
      return stream(
        `/api/conversations/${conversationId}/messages`,
        { client_message_id: clientId, content: text },
        assistantTemp,
        userTemp,
      );
    },
    [conversationId, stream],
  );

  const retry = useCallback(
    async (assistantId: string) => {
      if (!conversationId || runningRef.current) return;
      patch(assistantId, (m) => ({ ...m, status: "streaming", content: "", error: undefined }));
      await stream(`/api/conversations/${conversationId}/messages/${assistantId}/retry`, undefined, assistantId, null);
    },
    [conversationId, stream],
  );

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  return {
    messages,
    isRunning,
    serverBusy,
    isLoading: !!conversationId && query.isLoading,
    loadError: query.error,
    notice,
    dismissNotice: () => setNotice(null),
    send,
    retry,
    cancel,
  };
}
