import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NULL_PLACEHOLDER } from "@/lib/format";

interface MissingValueProps<T extends string | number> {
  value: T | null | undefined;
  format?: (v: T) => string;
  /** `value` `null` olduğunda gösterilecek açıklama. */
  reason?: string;
}

const DEFAULT_REASON = "Bu veri bankanın kamuya açık sayfasında yayımlanmamıştır.";

/**
 * ⚠️ `null` ile `0` ASLA karıştırılmaz: `0` gerçek bir değerdir (ör. Albaraka'nın
 * Togg kampanyasında finansman oranı gerçekten %0), `null` bankanın veriyi
 * yayımlamadığı anlamına gelir. Bu bileşen yalnızca `null`/`undefined` için
 * ipuçlu "—" gösterir; `0` dahil her gerçek değer olduğu gibi biçimlenip basılır.
 */
export function MissingValue<T extends string | number>({
  value,
  format,
  reason = DEFAULT_REASON,
}: MissingValueProps<T>) {
  if (value === null || value === undefined) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-text-400" tabIndex={0}>
            {NULL_PLACEHOLDER}
          </span>
        </TooltipTrigger>
        <TooltipContent>{reason}</TooltipContent>
      </Tooltip>
    );
  }

  return <>{format ? format(value) : value}</>;
}
