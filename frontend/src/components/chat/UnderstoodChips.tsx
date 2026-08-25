import { X } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { taxonomyLabel } from "@/lib/taxonomy";
import type { UnderstoodFilter } from "@/types/api";

interface UnderstoodChipsProps {
  filters: UnderstoodFilter[];
  /** Bir çip kaldırıldığında; sorgu bu süzgeç olmadan yeniden çalıştırılır. */
  onRemove: (filter: UnderstoodFilter) => void;
}

/**
 * "Anladığım" çipleri — sistemin soruyu nasıl süzgece çevirdiğini gösterir.
 *
 * ⚠️ BU BİR SÜS DEĞİL. Eski arayüz sorguyu sessizce üç kelimeye indirip
 * `ILIKE` ile arıyordu; kullanıcı yanlış anlaşılmayı göremiyor, dolayısıyla
 * düzeltemiyordu. Çipler yorumu görünür ve DÜZELTİLEBİLİR kılar.
 *
 * ⚠️ Her çipin ipucunda, sorgunun o süzgeci üreten parçası yazar. Kaynağı
 * gösterilemeyen bir süzgeç, kaynağı gösterilemeyen bir sonuç demektir.
 */
/**
 * Süzgecin nereden geldiğini açıklar.
 *
 *  Devralınan bağlam sorguda GEÇEN bir ifade değildir. "Sorgudaki 'önceki
 * cevap' ifadesinden çıkarıldı" demek kullanıcıya yanlış bilgi verir ve
 * yanlış devralmayı fark etmesini engeller.
 */
function kanitAciklamasi(evidence: string): string {
  if (evidence === "önceki soru") {
    return "Bu soruda belirtilmedi; önceki sorunuzdan devralındı.";
  }
  if (evidence === "önceki cevap") {
    return "Bu soruda belirtilmedi; önceki yanıtın işaret ettiği kurumdan alındı.";
  }
  return `Sorgudaki “${evidence}” ifadesinden çıkarıldı.`;
}

export function UnderstoodChips({ filters, onRemove }: UnderstoodChipsProps) {
  if (filters.length === 0) {
    return (
      <p className="text-xs text-text-500">
        Sorguda yapısal süzgeç bulunamadı; arama serbest metin üzerinden yapıldı.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-medium text-text-500">Anladığım:</span>
      {filters.map((filter) => (
        <Tooltip key={`${filter.kind}-${filter.value}`}>
          <TooltipTrigger asChild>
            <span className="inline-flex items-center gap-1 rounded border border-border bg-neutral-50 py-0.5 pl-2 pr-1 text-xs text-text-900">
              <span className="text-text-500">{filter.label}:</span>
              <span className="font-medium">{taxonomyLabel(filter.display)}</span>
              <button
                type="button"
                onClick={() => onRemove(filter)}
                aria-label={`${filter.label} süzgecini kaldır`}
                className="ml-0.5 rounded p-0.5 text-text-500 transition-colors hover:bg-border hover:text-text-900"
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <div className="max-w-xs space-y-1">
              <div>{kanitAciklamasi(filter.evidence)}</div>
              <div className="text-text-500">
                Kaldırmak için çipteki çarpıya tıklayın; sorgu bu süzgeç olmadan
                yeniden çalışır.
              </div>
            </div>
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
