import { Check, LogOut, MessageSquarePlus, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import { useAuthActions, useSession } from "../auth/useSession";
import { useConversations, useDeleteConversation, useUpdateConversation } from "./queries";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const conversations = useConversations();
  const session = useSession();
  const { logout } = useAuthActions();
  const navigate = useNavigate();

  return (
    <nav aria-label="Conversations" className="flex h-full flex-col bg-muted/50">
      <div className="p-3">
        <Button
          className="w-full justify-start"
          variant="outline"
          onClick={() => {
            navigate("/");
            onNavigate?.();
          }}
        >
          <MessageSquarePlus className="size-4" /> New chat
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {conversations.isLoading && <p className="px-3 py-2 text-sm text-muted-foreground">Loading…</p>}
        {conversations.error && (
          <p className="px-3 py-2 text-sm text-destructive">Could not load conversations.</p>
        )}
        {conversations.data?.length === 0 && (
          <p className="px-3 py-2 text-sm text-muted-foreground">No conversations yet.</p>
        )}
        <ul className="space-y-0.5" data-testid="conversation-list">
          {conversations.data?.map((c) => (
            <ConversationItem key={c.id} id={c.id} title={c.title} onNavigate={onNavigate} />
          ))}
        </ul>
      </div>
      <div className="flex items-center gap-2 border-t p-3">
        <span className="flex-1 truncate text-sm text-muted-foreground" title={session.data?.email}>
          {session.data?.email}
        </span>
        <Button variant="ghost" size="icon-sm" aria-label="Sign out" onClick={() => logout.mutate()}>
          <LogOut className="size-4" />
        </Button>
      </div>
    </nav>
  );
}

function ConversationItem({ id, title, onNavigate }: { id: string; title: string; onNavigate?: () => void }) {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const update = useUpdateConversation();
  const remove = useDeleteConversation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  if (editing) {
    const save = () => {
      const next = draft.trim();
      if (next && next !== title) update.mutate({ id, body: { title: next } });
      setEditing(false);
    };
    return (
      <li className="flex items-center gap-1 px-1">
        <Input
          autoFocus
          aria-label="Conversation title"
          value={draft}
          maxLength={200}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") save();
            if (e.key === "Escape") setEditing(false);
          }}
          className="h-8"
        />
        <Button size="icon-sm" variant="ghost" aria-label="Save title" onClick={save}>
          <Check className="size-4" />
        </Button>
        <Button size="icon-sm" variant="ghost" aria-label="Cancel rename" onClick={() => setEditing(false)}>
          <X className="size-4" />
        </Button>
      </li>
    );
  }

  return (
    <li className="group relative">
      <NavLink
        to={`/c/${id}`}
        onClick={onNavigate}
        className={({ isActive }) =>
          cn(
            "block truncate rounded-md px-3 py-2 pr-16 text-sm hover:bg-accent",
            isActive && "bg-accent font-medium",
          )
        }
      >
        {title}
      </NavLink>
      <div className="absolute right-1 top-1/2 hidden -translate-y-1/2 gap-0.5 group-focus-within:flex group-hover:flex">
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={`Rename ${title}`}
          onClick={() => {
            setDraft(title);
            setEditing(true);
          }}
        >
          <Pencil className="size-3.5" />
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={`Delete ${title}`}
          onClick={() => {
            if (!window.confirm(`Delete "${title}"? This cannot be undone.`)) return;
            remove.mutate(id, {
              onSuccess: () => {
                if (conversationId === id) navigate("/");
              },
            });
          }}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
    </li>
  );
}
