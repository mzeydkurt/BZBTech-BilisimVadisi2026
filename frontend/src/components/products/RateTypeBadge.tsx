import { cn } from "@/lib/utils";
import type { RateType } from "@/types/api";

const LABELS: Record<RateType, string> = {
  financing_rate: "Finansman maliyeti · aylık",
  participation_yield: "Katılma getirisi · yıllık",
  profit_sharing_ratio: "Katılımcı payı",
};

const CLASSES: Record<RateType, string> = {
  financing_rate: "border-brand-700/30 bg-teal-100 text-brand-900",
  participation_yield: "border-teal-500/30 bg-teal-100 text-brand-900",
  profit_sharing_ratio: "border-warn-600/30 bg-surface text-warn-600",
};

/**
 * ⚠️ Zorunlu etiket: aynı `profit_rate_pct` sütunu finansman maliyeti,
 * katılma getirisi ya da kâr paylaşım oranı gibi üç farklı şeyi taşıyabilir.
 * Etiketsiz gösterilen bir oran yanıltıcıdır — %3,05 maliyet ile %31,22
 * getiri aynı görünür.
 */
export function RateTypeBadge({ rateType, className }: { rateType: string; className?: string }) {
  const known = LABELS[rateType as RateType] ? (rateType as RateType) : null;

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-xs font-medium",
        known ? CLASSES[known] : "border-border bg-surface text-text-500",
        className,
      )}
    >
      {known ? LABELS[known] : rateType}
    </span>
  );
}
