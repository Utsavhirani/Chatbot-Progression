import { AssistantRuntimeProvider, useExternalStoreRuntime, type ThreadMessageLike } from "@assistant-ui/react";
import { useQueryClient } from "@tanstack/react-query";
import { Settings2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { api } from "../../api/client";
import { Button } from "../../components/ui/button";
import { conversationsKey, useConversation } from "../conversations/queries";
import { SettingsPanel } from "./SettingsPanel";
import { ChatActionsContext } from "./chatActions";
import { Thread } from "./Thread";
import { describeRejection, useConversationChat, type UiMessage } from "./useConversationChat";

type PendingState = { pendingMessage?: string } | null;

function toThreadMessage(m: UiMessage): ThreadMessageLike {
  const status: ThreadMessageLike["status"] =
    m.role === "user"
      ? undefined
      : m.status === "streaming"
        ? { type: "running" }
        : m.status === "complete"
          ? { type: "complete", reason: "stop" }
          : m.status === "cancelled"
            ? { type: "incomplete", reason: "cancelled" }
            : { type: "incomplete", reason: "error", error: m.error?.message ?? null };
  return {
    id: m.id,
    role: m.role,
    content: [{ type: "text", text: m.content }],
    status,
    metadata: { custom: { error: m.error, note: m.note, serverStatus: m.status } },
  };
}

/**
 * One conversation (`/c/:id`), or a not-yet-created one (`/`): the conversation is created
 * on the first message, then we navigate to it and send that message there.
 */
export function ChatPage({ conversationId }: { conversationId?: string }) {
  const chat = useConversationChat(conversationId);
  const conversation = useConversation(conversationId);
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const sentPending = useRef(false);

  // Deliver the first message typed on the "new chat" screen once its conversation exists.
  const pending = (location.state as PendingState)?.pendingMessage;
  useEffect(() => {
    if (!conversationId || !pending || sentPending.current || chat.isLoading) return;
    sentPending.current = true;
    navigate(location.pathname, { replace: true, state: null });
    void chat.send(pending);
  }, [conversationId, pending, chat, navigate, location.pathname]);

  const onNew = async (text: string) => {
    if (conversationId) {
      await chat.send(text);
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const conv = await api.createConversation();
      void qc.invalidateQueries({ queryKey: conversationsKey });
      navigate(`/c/${conv.id}`, { state: { pendingMessage: text } });
    } catch (err) {
      setCreateError(describeRejection(err));
      setCreating(false);
    }
  };

  const runtime = useExternalStoreRuntime({
    messages: chat.messages,
    isRunning: chat.isRunning || creating,
    isDisabled: chat.isLoading,
    isSendDisabled: chat.serverBusy,
    convertMessage: toThreadMessage,
    onNew: async (message) => {
      const text = message.content
        .map((p) => (p.type === "text" ? p.text : ""))
        .join("")
        .trim();
      if (text) await onNew(text);
    },
    onCancel: async () => chat.cancel(),
  });

  if (chat.loadError) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        This conversation could not be loaded. It may have been deleted.
      </div>
    );
  }

  return (
    <ChatActionsContext.Provider value={{ retry: (id) => void chat.retry(id), isRunning: chat.isRunning }}>
      <AssistantRuntimeProvider runtime={runtime}>
        <div className="flex h-full min-h-0 flex-col">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4 md:px-6">
            <h1 className="flex-1 truncate text-sm font-medium" data-testid="conversation-title">
              {conversationId ? (conversation.data?.title ?? "…") : "New conversation"}
            </h1>
            {conversationId && conversation.data && (
              <span className="hidden text-xs text-muted-foreground sm:inline">{conversation.data.settings.model}</span>
            )}
            {conversationId && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Conversation settings"
                aria-expanded={showSettings}
                onClick={() => setShowSettings((v) => !v)}
              >
                <Settings2 className="size-4" />
              </Button>
            )}
          </header>
          <div className="flex min-h-0 flex-1">
            <div className="min-w-0 flex-1">
              <Thread
                loading={chat.isLoading || !!pending}
                notice={chat.notice ?? createError}
                onDismissNotice={() => {
                  chat.dismissNotice();
                  setCreateError(null);
                }}
              />
            </div>
            {showSettings && conversation.data && (
              <SettingsPanel conversation={conversation.data} onClose={() => setShowSettings(false)} />
            )}
          </div>
        </div>
      </AssistantRuntimeProvider>
    </ChatActionsContext.Provider>
  );
}
