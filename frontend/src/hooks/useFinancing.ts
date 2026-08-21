import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { FinancingQuery } from "@/types/api";

/** Finansmanlar sekmesi sorgusu (KATİP KAPI 6). */
export function useFinancing(query: FinancingQuery) {
  return useQuery({
    queryKey: ["financing", query],
    queryFn: () => api.financing(query),
    retry: 1,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}
