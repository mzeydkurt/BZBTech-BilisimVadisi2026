import { Info, type LucideIcon } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: number;
  icon?: LucideIcon;
  /** Değerin altında gösterilen kısa açıklama. */
  hint?: string;
  /** Başlıktaki (i) üzerine gelince görünen tanım. */
  info?: string;
  /** Vurgu rengi; varsayılan nötr. */
  tone?: "neutral" | "active" | "upcoming" | "expired" | "unknown";
}

const TONE_CLASSES: Record<NonNullable<StatCardProps["tone"]>, string> = {
  neutral: "text-text-900",
  active: "text-brand-500",
  upcoming: "text-teal-500",
  expired: "text-text-500",
  unknown: "text-warn-600",
};

/** Gösterge panelindeki tek sayısal ölçüt kartı. */
export function StatCard({
  label,
  value,
  icon: Icon,
  hint,
  info,
  tone = "neutral",
}: StatCardProps) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 text-sm text-text-500">
          {label}
          {info ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex shrink-0 rounded-full text-text-500 outline-none hover:text-text-900 focus-visible:ring-2 focus-visible:ring-brand-500/40"
                  aria-label={`${label}: açıklama`}
                  onClick={(e) => e.preventDefault()}
                  onPointerDown={(e) => e.stopPropagation()}
                >
                  <Info className="h-3 w-3" aria-hidden="true" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[240px] leading-relaxed">
                {info}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </span>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-text-500" aria-hidden="true" />}
      </div>

      <p className={cn("tabular mt-2 text-2xl font-semibold", TONE_CLASSES[tone])}>
        {formatNumber(value)}
      </p>

      {hint && <p className="mt-1 text-xs text-text-500">{hint}</p>}
    </div>
  );
}
