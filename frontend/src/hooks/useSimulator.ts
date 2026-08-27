import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useFinancingSimulation() {
  return useMutation({ mutationFn: api.simulateFinancing });
}

export function useYieldSimulation() {
  return useMutation({ mutationFn: api.simulateYield });
}

export function useBddkCheck() {
  return useMutation({ mutationFn: api.checkBddkLimit });
}

/**
 * BDDK değer bantları — arayüzde seçim listesi olarak sunulur.
 *
 * ⚠️ Bantlar SABİT YAZILMAZ, servisten okunur. BDDK kararı değiştiğinde tek
 * kaynak backend'in kanon dosyasıdır; iki yerde tutulan bir tablo,
 * güncellenmeyen tarafta sessizce yanlış limit gösterir.
 */
export function useBddkBands() {
  return useQuery({
    queryKey: ["bddk-bands"],
    queryFn: api.bddkBands,
    staleTime: Infinity,
  });
}
