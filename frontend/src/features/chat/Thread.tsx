import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import { AlertTriangle, ArrowUp, RotateCcw, Square, X } from "lucide-react";
import { useContext } from "react";
import remarkGfm from "remark-gfm";
import { Button } from "../../components/ui/button";
import { ChatActionsContext } from "./chatActions";
import type { UiError } from "./useConversationChat";

type Custom = { error?: UiError; note?: string; serverStatus?: string };

export function Thread({
  notice,
  onDismissNotice,
  loading,
}: {
  notice: string | null;
  onDismissNotice: () => void;
  loading: boolean;
}) {
  return (
    <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
      <ThreadPrimitive.Viewport className="flex flex-1 flex-col overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl flex-1 px-4 pt-6">
          <ThreadPrimitive.Empty>
            {loading ? (
              <p className="py-16 text-center text-sm text-muted-foreground">Loading conversation…</p>
            ) : (
              <Welcome />
            )}
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage }} />
        </div>
        <ThreadPrimitive.ViewportFooter className="sticky bottom-0 mx-auto w-full max-w-3xl bg-background px-4 pb-4 pt-2">
          {notice && (
            <div
              role="alert"
              data-testid="send-notice"
              className="mb-2 flex items-start gap-2 rounded-md bg-destructive-muted px-3 py-2 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span className="flex-1">{notice}</span>
              <button aria-label="Dismiss" onClick={onDismissNotice} className="cursor-pointer">
                <X className="size-4" />
              </button>
            </div>
          )}
          <Composer />
          <p className="mt-2 text-center text-xs text-muted-foreground">
            AI answers can be wrong. Verify important details.
          </p>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

function Welcome() {
  return (
    <div className="flex h-full flex-col items-center justify-center py-16 text-center">
      <h2 className="text-2xl font-semibold">How can we help?</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Ask about orders, deliveries, returns or anything else. Your conversations are saved so you can come back
        later.
      </p>
    </div>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="mb-5 flex justify-end" data-testid="user-message">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

function MarkdownText() {
  return <MarkdownTextPrimitive remarkPlugins={[remarkGfm]} className="prose-chat" />;
}

function AssistantMessage() {
  const id = useAuiState((s) => s.message.id);
  const isLast = useAuiState((s) => s.message.isLast);
  const running = useAuiState((s) => s.message.status?.type === "running");
  const hasText = useAuiState((s) => s.message.content.some((p) => p.type === "text" && p.text.length > 0));
  const custom = useAuiState((s) => s.message.metadata?.custom as Custom | undefined);
  const { retry, isRunning } = useContext(ChatActionsContext);
  const error = custom?.error;

  return (
    <MessagePrimitive.Root className="mb-5 flex justify-start" data-testid="assistant-message">
      <div className="max-w-[90%] min-w-0">
        {hasText && (
          <div className="break-words rounded-2xl rounded-bl-md bg-muted px-4 py-2.5">
            <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
          </div>
        )}
        {running && !hasText && <TypingDots />}
        {custom?.note && (
          <p data-testid="message-note" className="mt-1.5 px-1 text-xs text-muted-foreground">
            {custom.note}
          </p>
        )}
        {error && (
          <div
            data-testid="message-error"
            className="mt-2 flex flex-wrap items-center gap-2 text-sm text-destructive"
          >
            <AlertTriangle className="size-4" />
            <span>{error.message}</span>
            {error.retryable && isLast && !isRunning && !id.startsWith("local-") && (
              <Button size="sm" variant="outline" onClick={() => retry(id)} className="text-foreground">
                <RotateCcw className="size-3.5" /> Retry
              </Button>
            )}
          </div>
        )}
      </div>
    </MessagePrimitive.Root>
  );
}

function TypingDots() {
  return (
    <div aria-label="Assistant is typing" className="flex gap-1 rounded-2xl rounded-bl-md bg-muted px-4 py-3.5">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="flex items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring">
      <ComposerPrimitive.Input
        rows={1}
        autoFocus
        placeholder="Type your message…"
        aria-label="Message"
        className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
      />
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send asChild>
          <Button size="icon" aria-label="Send" className="rounded-full">
            <ArrowUp className="size-4" />
          </Button>
        </ComposerPrimitive.Send>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel asChild>
          <Button size="icon" variant="outline" aria-label="Stop" className="rounded-full">
            <Square className="size-3.5 fill-current" />
          </Button>
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
    </ComposerPrimitive.Root>
  );
}
