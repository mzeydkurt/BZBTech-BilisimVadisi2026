import { useMutation } from "@tanstack/react-query";

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
