import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../../api/client";
import type { User } from "../../api/types";

export const meKey = ["me"] as const;

/** Current user from the session cookie; `null` when signed out. */
export function useSession() {
  return useQuery<User | null>({
    queryKey: meKey,
    queryFn: async () => {
      try {
        return await api.me();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAuthActions() {
  const qc = useQueryClient();
  // Drop every cached query except the session itself, so no previous user's data is ever shown.
  // (qc.clear() would also detach the mounted session observer and the UI would not react.)
  const resetUserData = () => qc.removeQueries({ predicate: (q) => q.queryKey[0] !== meKey[0] });
  const onSignedIn = (user: User) => {
    resetUserData();
    qc.setQueryData(meKey, user);
  };
  const login = useMutation({
    mutationFn: (v: { email: string; password: string }) => api.login(v.email, v.password),
    onSuccess: onSignedIn,
  });
  const register = useMutation({
    mutationFn: (v: { email: string; password: string }) => api.register(v.email, v.password),
    onSuccess: onSignedIn,
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      qc.setQueryData(meKey, null);
      resetUserData();
    },
  });
  return { login, register, logout };
}
