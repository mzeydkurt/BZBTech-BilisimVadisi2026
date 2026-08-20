import { AlertTriangle } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMonths } from "@/lib/format";

/**
 * `is_exact_term_match: false` — oran istenen vade için değil, başka bir
 * vade için yayımlanmış ve uyarlanmış. Bu bilgi gizlenmez, satırda görünür
 * bir uyarı ikonu + tooltip olarak gösterilir.
 */
export function ExactTermMatchWarning({ ratePublishedForMonths }: { ratePublishedForMonths: number | null }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-help text-warn-600" tabIndex={0}>
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Bu oran {formatMonths(ratePublishedForMonths)} vadesi için yayımlanmıştır, istenen vadeye
        uyarlanmıştır.
      </TooltipContent>
    </Tooltip>
  );
}
