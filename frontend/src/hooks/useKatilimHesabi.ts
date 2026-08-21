import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { KatilimHesabiQuery } from "@/types/api";

/** Katılım Hesabı sekmesi pivot sorgusu (KATİP KAPI 7). */
export function useKatilimHesabi(query: KatilimHesabiQuery) {
  return useQuery({
    queryKey: ["katilim-hesabi", query],
    queryFn: () => api.katilimHesabi(query),
    retry: 1,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}
