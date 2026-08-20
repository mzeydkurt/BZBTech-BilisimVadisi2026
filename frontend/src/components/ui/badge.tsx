import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Rozet varyantları.
 *
 * ⚠️ `unknown` varyantı `expired`dan GÖRSEL OLARAK AYRIDIR (sarı kenarlıklı,
 * dolgusuz). Tarihi bulunmayan kampanyayı "süresi dolmuş" gibi göstermek
 * yanlış bilgi olurdu — Türkiye Finans'ın hiçbir kampanyasında tarih yok.
 */
const badgeVariants = cva(
  "inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        active: "bg-brand-500 text-white",
        upcoming: "bg-teal-500 text-white",
        expired: "bg-neutral-50 text-text-500 border border-border",
        unknown: "bg-surface text-warn-600 border border-warn-600",
        neutral: "bg-neutral-50 text-text-500 border border-border",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

/** `forwardRef` gereklidir: `TooltipTrigger asChild` gibi Radix sarmalayıcılar ref iletir. */
export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, ...props }, ref) => (
    <span ref={ref} className={cn(badgeVariants({ variant }), className)} {...props} />
  ),
);
Badge.displayName = "Badge";
