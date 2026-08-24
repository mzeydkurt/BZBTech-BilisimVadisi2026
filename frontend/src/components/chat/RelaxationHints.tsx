import { Filter } from "lucide-react";

import { taxonomyLabel } from "@/lib/taxonomy";
import type { RelaxationHintOut, UnderstoodFilter } from "@/types/api";

interface RelaxationHintsProps {
  hints: RelaxationHintOut[];
  understood: UnderstoodFilter[];
  onRelax: (hint: RelaxationHintOut) => void;
}

/**
 * Boş sonuçta "hangi süzgeci kaldırırsan ne çıkar" önerileri.
 *
 * ⚠️ SÜZGEÇ KENDİLİĞİNDEN GEVŞETİLMEZ. "KT'de akaryakıt indirimi" sorgusunda
 * Kuveyt Türk'ün 3 akaryakıt kampanyası VAR ama hiçbiri indirim etiketi
 * taşımıyor. Sonucu kendi başına gevşetip 3 kaydı göstermek, kullanıcının
 * sormadığı soruyu yanıtlamak olur; boş göstermek ise "banka bunu yapmıyor"
 * izlenimi verir. Üçüncü yol: kararı kullanıcıya bırakmak.
 */
export function RelaxationHints({ hints, understood, onRelax }: RelaxationHintsProps) {
  if (hints.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="flex items-center gap-1.5 text-sm font-medium text-text-900">
        <Filter className="h-4 w-4 text-text-500" aria-hidden="true" />
        Süzgeçlerden birini kaldırırsanız sonuç var
      </p>

      <ul className="mt-2 space-y-1.5">
        {hints.map((oneri) => {
          const cip = understood.find((filtre) => filtre.kind === oneri.kind);
          const gosterim = cip ? taxonomyLabel(cip.display) : oneri.value;
          return (
            <li key={`${oneri.kind}-${oneri.value}`}>
              <button
                type="button"
                onClick={() => onRelax(oneri)}
                className="w-full rounded border border-border px-3 py-2 text-left text-sm text-text-900 transition-colors hover:border-brand-500 hover:bg-neutral-50"
              >
                <span className="text-text-500">{oneri.label}:</span>{" "}
                <span className="font-medium">{gosterim}</span>{" "}
                <span className="text-text-500">süzgecini kaldır →</span>{" "}
                <span className="tabular-nums font-medium text-brand-700">
                  {oneri.hit_count} sonuç
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
