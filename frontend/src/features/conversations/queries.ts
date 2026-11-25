import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Conversation, ModelSettings } from "../../api/types";

export const conversationsKey = ["conversations"] as const;
export const conversationKey = (id: string) => ["conversation", id] as const;

export function useConversations() {
  return useQuery({ queryKey: conversationsKey, queryFn: api.conversations });
}

export function useConversation(id: string | undefined) {
  return useQuery({ queryKey: conversationKey(id ?? "none"), queryFn: () => api.conversation(id!), enabled: !!id });
}

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: api.models, staleTime: Infinity });
}

export function useUpdateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: string;
      body: { title?: string; system_prompt?: string | null; settings?: Partial<ModelSettings> };
    }) => api.updateConversation(v.id, v.body),
    onSuccess: (conv: Conversation) => {
      qc.setQueryData(conversationKey(conv.id), conv);
      void qc.invalidateQueries({ queryKey: conversationsKey });
    },
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: (_: void, id: string) => {
      qc.removeQueries({ queryKey: conversationKey(id) });
      void qc.invalidateQueries({ queryKey: conversationsKey });
    },
  });
}
