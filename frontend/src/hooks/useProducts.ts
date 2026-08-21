import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useProduct(id: number | null) {
  return useQuery({
    queryKey: ["product", id],
    queryFn: () => api.product(id as number),
    enabled: id !== null,
    retry: 1,
    staleTime: 30_000,
  });
}
