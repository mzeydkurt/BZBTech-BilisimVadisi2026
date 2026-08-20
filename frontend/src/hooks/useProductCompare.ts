import { useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api";

/** Ürün karşılaştırma motoru; kullanıcı formu gönderince tetiklenir (GET değil). */
export function useProductCompare() {
  return useMutation({ mutationFn: api.compareProducts });
}
