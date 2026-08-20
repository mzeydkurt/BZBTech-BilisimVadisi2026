import { useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useChat() {
  return useMutation({ mutationFn: api.chat });
}
