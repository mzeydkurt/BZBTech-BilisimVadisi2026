import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { KatilimHesabiTable } from "@/components/katilimHesabi/KatilimHesabiTable";
import { RankedProductTable } from "@/components/compare/RankedProductTable";
import { useKatilimHesabi } from "@/hooks/useKatilimHesabi";
import { useProductCompare } from "@/hooks/useProductCompare";
import type { KatilimHesabiRateType, KatilimHesabiVariant } from "@/types/api";

const RATE_TYPE_OPTIONS: { value: KatilimHesabiRateType; label: string }[] = [
  { value: "participation_yield", label: "Dağıtılan Kâr Payı Oranı (getiri)" },
  { value: "profit_sharing_ratio", label: "Kâr Paylaşım Oranı (bölüşüm)" },
];

const VARIANT_OPTIONS: { value: KatilimHesabiVariant; label: string }[] = [
  { value: "normal", label: "Standart Katılma Hesabı" },
  { value: "ara_odemeli", label: "Ara Ödemeli Katılma Hesabı" },
];

const TERM_OPTIONS: { value: number; label: string }[] = [
  { value: 1, label: "1 Ay" },
  { value: 3, label: "3 Ay" },
  { value: 6, label: "6 Ay" },
  { value: 12, label: "1 Yıl" },
];

export function KatilimHesabiPage() {
  const [rateType, setRateType] = useState<KatilimHesabiRateType>("participation_yield");
  const [variant, setVariant] = useState<KatilimHesabiVariant>("normal");
  const [calculatorTerm, setCalculatorTerm] = useState(12);

  const { data, isLoading, isError, error, refetch } = useKatilimHesabi({
    rate_type: rateType,
    variant,
  });
  const mutation = useProductCompare();

  const criterion = rateType === "participation_yield" ? "en_yuksek_getiri" : "en_yuksek_paylasim_orani";

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Katılım Hesabı</h1>
        <p className="mt-1 text-sm text-text-500">
          TKBB Veri Peteği'nin resmi verisi ve bankaların kendi sitelerinden toplanan katılma
          hesabı oranları — aynı ekranda, kaynağı belirtilerek.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4">
        <div className="w-72">
          <label htmlFor="katilim-rate-type" className="mb-1 block text-sm text-text-500">
            Oran Türü
          </label>
          <Select value={rateType} onValueChange={(next) => setRateType(next as KatilimHesabiRateType)}>
            <SelectTrigger id="katilim-rate-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RATE_TYPE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-64">
          <label htmlFor="katilim-variant" className="mb-1 block text-sm text-text-500">
            Ürün
          </label>
          <Select value={variant} onValueChange={(next) => setVariant(next as KatilimHesabiVariant)}>
            <SelectTrigger id="katilim-variant">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VARIANT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {isLoading && <LoadingState variant="table" />}

      {isError && <ErrorState error={error} onRetry={() => void refetch()} />}

      {!isLoading && !isError && data && data.rows.length === 0 && (
        <EmptyState
          title="Bu filtrelerle veri bulunamadı"
          description="Farklı bir oran türü veya ürün deneyebilirsiniz."
        />
      )}

      {!isLoading && !isError && data && data.rows.length > 0 && (
        <KatilimHesabiTable rows={data.rows} />
      )}

      {data && variant === "ara_odemeli" && data.not_offered_banks.length > 0 && (
        <p className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-text-500">
          Ara ödemeli katılma hesabı şu bankalarda sunulmuyor (veri eksik değil, ürün yok):{" "}
          {data.not_offered_banks.join(", ")}
        </p>
      )}

      {data && data.data_quality_notes.length > 0 && (
        <div className="rounded-lg border border-warn-600/30 bg-surface px-4 py-3 text-sm text-warn-600">
          <p className="font-medium">Veri kalitesi notları</p>
          <ul className="mt-1 list-inside list-disc">
            {data.data_quality_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-900">
          Bu vadede hangi banka en avantajlı?
        </h2>
        <p className="mt-1 text-xs text-text-500">
          Mevcut ürün karşılaştırma motorunu (`/products/compare`) kullanır; ayrı bir
          sıralama algoritması yoktur.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div className="w-40">
            <label htmlFor="katilim-calc-term" className="mb-1 block text-sm text-text-500">
              Vade
            </label>
            <Select
              value={String(calculatorTerm)}
              onValueChange={(next) => setCalculatorTerm(Number(next))}
            >
              <SelectTrigger id="katilim-calc-term">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TERM_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="secondary"
            size="sm"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate({
                rate_type: rateType,
                criterion,
                term_months: calculatorTerm,
                currency: "TRY",
              })
            }
          >
            {mutation.isPending ? "Hesaplanıyor…" : "En avantajlıyı bul"}
          </Button>
        </div>

        {mutation.isError && <ErrorState error={mutation.error} title="Hesaplanamadı" />}

        {mutation.isSuccess && (
          <div className="mt-3 space-y-3">
            {mutation.data.winner_reason && (
              <p className="rounded-md bg-teal-100 px-3 py-2 text-sm text-brand-900">
                {mutation.data.winner_reason}
              </p>
            )}
            {mutation.data.ranked.length > 0 ? (
              <RankedProductTable
                items={mutation.data.ranked}
                winnerId={mutation.data.winner?.product_id}
              />
            ) : (
              <p className="text-sm text-text-500">{mutation.data.note}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
