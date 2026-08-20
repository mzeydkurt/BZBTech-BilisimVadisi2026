import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { ProductQuery } from "@/types/api";

/** Ürün kataloğu sorgusu. */
export function useProducts(query: ProductQuery) {
  return useQuery({
    queryKey: ["products", query],
    queryFn: () => api.products(query),
    retry: 1,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}

export function useProduct(id: number | null) {
  return useQuery({
    queryKey: ["product", id],
    queryFn: () => api.product(id as number),
    enabled: id !== null,
    retry: 1,
    staleTime: 30_000,
  });
}
