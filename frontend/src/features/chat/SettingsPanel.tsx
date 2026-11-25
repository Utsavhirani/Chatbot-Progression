import { X } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { Conversation } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Input, Label, Textarea } from "../../components/ui/input";
import { useModels, useUpdateConversation } from "../conversations/queries";

/** Per-conversation model settings and system prompt (validated again by the backend). */
export function SettingsPanel({ conversation, onClose }: { conversation: Conversation; onClose: () => void }) {
  const models = useModels();
  const update = useUpdateConversation();
  const [model, setModel] = useState(conversation.settings.model);
  const [temperature, setTemperature] = useState(conversation.settings.temperature);
  const [maxTokens, setMaxTokens] = useState(conversation.settings.max_tokens);
  const [systemPrompt, setSystemPrompt] = useState(conversation.system_prompt ?? "");
  const selected = models.data?.models.find((m) => m.id === model);

  const changeModel = (id: string) => {
    setModel(id);
    const info = models.data?.models.find((m) => m.id === id);
    if (info) setMaxTokens(info.default_max_tokens);
  };

  const save = (e: FormEvent) => {
    e.preventDefault();
    update.mutate({
      id: conversation.id,
      body: {
        system_prompt: systemPrompt.trim() || null,
        settings: { model, temperature, max_tokens: maxTokens },
      },
    });
  };

  return (
    <aside
      aria-label="Conversation settings"
      className="fixed inset-0 z-30 flex flex-col overflow-y-auto bg-background md:static md:w-80 md:shrink-0 md:border-l"
    >
      <div className="flex h-12 items-center justify-between border-b px-4">
        <h2 className="text-sm font-medium">Settings</h2>
        <Button variant="ghost" size="icon-sm" aria-label="Close settings" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <form onSubmit={save} className="space-y-5 p-4">
        <div className="space-y-1.5">
          <Label htmlFor="model">Model</Label>
          <select
            id="model"
            value={model}
            onChange={(e) => changeModel(e.target.value)}
            className="h-9 w-full rounded-md border bg-background px-2 text-sm"
          >
            {models.data?.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="temperature">Temperature: {temperature.toFixed(1)}</Label>
          <input
            id="temperature"
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
            className="w-full accent-primary"
          />
          <p className="text-xs text-muted-foreground">Lower is more focused, higher is more creative.</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="max-tokens">Max reply length (tokens)</Label>
          <Input
            id="max-tokens"
            type="number"
            min={1}
            max={selected?.max_output_tokens}
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
          />
          {selected?.reasoning && (
            <p className="text-xs text-muted-foreground">Reasoning model: hidden reasoning also uses this budget.</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="system-prompt">System prompt</Label>
          <Textarea
            id="system-prompt"
            rows={6}
            maxLength={4000}
            placeholder="e.g. You are a friendly support assistant for Acme Widgets."
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
        {update.error && (
          <p role="alert" className="text-sm text-destructive">
            {update.error.message}
          </p>
        )}
        {update.isSuccess && !update.isPending && <p className="text-sm text-muted-foreground">Saved.</p>}
        <Button type="submit" disabled={update.isPending} className="w-full">
          {update.isPending ? "Saving…" : "Save settings"}
        </Button>
      </form>
    </aside>
  );
}
