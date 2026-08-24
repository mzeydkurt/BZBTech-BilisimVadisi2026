import { useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api";

/** Kampanya karşılaştırma motoru (§5.7 ödül / iade / taksit ölçütleri). */
export function useCampaignCompare() {
  return useMutation({ mutationFn: api.compareCampaigns });
}
