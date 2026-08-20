import { useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useExtract() {
  return useMutation({ mutationFn: api.extract });
}
