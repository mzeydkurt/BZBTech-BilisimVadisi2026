import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export const CHAT_SESSION_STORAGE_KEY = "katibim.session_id";

export function useChat() {
  return useMutation({ mutationFn: api.chat });
}

export function useChatSession(sessionKey: string | null) {
  return useQuery({
    queryKey: ["chat-session", sessionKey],
    queryFn: () => api.getChatSession(sessionKey as string),
    enabled: Boolean(sessionKey),
    retry: 1,
    staleTime: 0,
  });
}

export function useCreateChatSession() {
  return useMutation({ mutationFn: api.createChatSession });
}

export function useEndChatSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionKey: string) => api.endChatSession(sessionKey),
    onSuccess: (_data, sessionKey) => {
      void queryClient.removeQueries({ queryKey: ["chat-session", sessionKey] });
    },
  });
}

export function readStoredSessionId(): string | null {
  try {
    return localStorage.getItem(CHAT_SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function writeStoredSessionId(sessionId: string | null): void {
  try {
    if (sessionId) localStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId);
    else localStorage.removeItem(CHAT_SESSION_STORAGE_KEY);
  } catch {
    // localStorage kapalıysa yalnızca bellek içi oturum devam eder.
  }
}
