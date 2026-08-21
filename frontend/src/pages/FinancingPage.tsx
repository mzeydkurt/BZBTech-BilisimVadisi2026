import { useState } from "react";

import {
  FinancingFilters,
  type FinancingFilterState,
} from "@/components/financing/FinancingFilters";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { ProductTable } from "@/components/products/ProductTable";
import { useBanks } from "@/hooks/useBanks";
import { useFinancing } from "@/hooks/useFinancing";

export function FinancingPage() {
  const [filters, setFilters] = useState<FinancingFilterState>({});

  const { data: banks } = useBanks();
  const { data, isLoading, isError, error, refetch } = useFinancing(filters);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Finansmanlar</h1>
        <p className="mt-1 text-sm text-text-500">
          Konut, taşıt, ihtiyaç, arsa ve diğer finansman ürünleri — kâr payı oranı ve
          limit bilgisiyle. Katılma hesabı ürünleri bu sekmede yer almaz.
        </p>
      </div>

      <FinancingFilters banks={banks ?? []} value={filters} onChange={setFilters} />

      {isLoading && <LoadingState variant="table" />}

      {isError && <ErrorState error={error} onRetry={() => void refetch()} />}

      {!isLoading && !isError && data && data.financing.length === 0 && (
        <EmptyState
          title="Filtrelere uyan finansman ürünü bulunamadı"
          description="Farklı bir banka veya finansman türü deneyebilirsiniz."
          onClear={() => setFilters({})}
        />
      )}

      {!isLoading && !isError && data && data.financing.length > 0 && (
        <>
          <p className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-text-500">
            {data.coverage_note}
          </p>

          <ProductTable products={data.financing} />

          {data.no_data_products.length > 0 && (
            <details className="rounded-lg border border-border bg-surface p-4 text-sm">
              <summary className="cursor-pointer font-medium text-text-900">
                Ne oran ne limit bilgisi yayımlanan {data.no_data_products.length} ürün
              </summary>
              <ul className="mt-2 list-inside list-disc space-y-1 text-text-500">
                {data.no_data_products.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
