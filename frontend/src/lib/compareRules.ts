import type { ComparableRateType, RankingCriterion } from "@/types/api";

/**
 * ⚠️ DONDURULMUŞ SÖZLEŞME: her ölçüt yalnızca belirli bir oran türüyle uyumludur
 * (`en_yuksek_getiri` + `financing_rate` gibi bağdaşmaz bir çift backend'de 422
 * döner). Arayüz kullanıcıya baştan geçersiz bir kombinasyon SUNMAMALI.
 */
export const CRITERIA_LABELS: Record<RankingCriterion, string> = {
  en_dusuk_kar_payi: "En düşük kâr payı oranı",
  en_dusuk_masraf: "En düşük tahsis ücreti/oranı",
  en_dusuk_toplam_maliyet: "En düşük toplam maliyet",
  en_yuksek_getiri: "En yüksek getiri",
  en_yuksek_paylasim_orani: "En yüksek paylaşım oranı",
  en_uzun_vade: "En uzun vade",
  en_avantajli: "En avantajlı (ağırlıklı)",
};

const CRITERIA_BY_RATE_TYPE: Record<ComparableRateType, RankingCriterion[]> = {
  financing_rate: [
    "en_dusuk_kar_payi",
    "en_dusuk_masraf",
    "en_dusuk_toplam_maliyet",
    "en_uzun_vade",
    "en_avantajli",
  ],
  participation_yield: ["en_yuksek_getiri", "en_uzun_vade", "en_avantajli"],
  profit_sharing_ratio: ["en_yuksek_paylasim_orani", "en_uzun_vade", "en_avantajli"],
};

/** Seçili oran türüyle bağdaşan ölçüt listesini döner. */
export function getValidCriteria(rateType: ComparableRateType): RankingCriterion[] {
  return CRITERIA_BY_RATE_TYPE[rateType];
}
