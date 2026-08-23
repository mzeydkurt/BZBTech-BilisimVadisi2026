import { useState } from "react";

import {
  FinancingFilters,
  type FinancingFilterState,
} from "@/components/financing/FinancingFilters";
import { BddkLimitsPanel } from "@/components/financing/BddkLimitsBanner";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { ProductTable } from "@/components/products/ProductTable";
import { useBanks } from "@/hooks/useBanks";
import { useFinancing } from "@/hooks/useFinancing";

/** product_type → BDDK aile anahtarı */
function familyFromProductType(productType?: string): string | null {
  if (!productType) return null;
  if (productType.includes("ihtiyac") || productType.includes("alisveris") || productType.includes("egitim")) {
    return "ihtiyac";
  }
  if (
    productType.includes("konut") ||
    productType.includes("gayrimenkul") ||
    productType.includes("arsa") ||
    productType.includes("isyeri")
  ) {
    return "konut";
  }
  if (productType.includes("tasit") || productType.includes("arac") || productType.includes("marka")) {
    return "tasit";
  }
  return null;
}

export function FinancingPage() {
  const [filters, setFilters] = useState<FinancingFilterState>({});

  const { data: banks } = useBanks();
  const { data, isLoading, isError, error, refetch } = useFinancing(filters);

  const activeFamily = familyFromProductType(filters.product_type);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Finansmanlar</h1>
        <p className="mt-1 text-sm text-text-500">
          Konut, taşıt, ihtiyaç ve diğer finansman ürünleri — kâr payı ve limit. Katılma
          hesabı bu sekmede yok.
        </p>
      </div>

      <FinancingFilters banks={banks ?? []} value={filters} onChange={setFilters} />

      {data && Object.keys(data.bddk_limits_by_family).length > 0 && (
        <BddkLimitsPanel
          byFamily={data.bddk_limits_by_family}
          activeFamily={activeFamily}
        />
      )}

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
          <p className="text-sm text-text-500">{data.coverage_note}</p>

          <ProductTable products={data.financing} />

          {data.products_with_limits_only.length > 0 && (
            <details className="rounded-lg border border-border bg-surface p-4 text-sm">
              <summary className="cursor-pointer font-medium text-text-900">
                Yalnızca limit (oran yok) — {data.products_with_limits_only.length} ürün
              </summary>
              <p className="mt-2 text-text-500">
                Tutar/vade bilgisi var; kâr payı oranı banka sayfasında yayımlanmamış.
              </p>
              <ul className="mt-2 list-inside list-disc space-y-1 text-text-500">
                {data.products_with_limits_only.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </details>
          )}

          {data.no_data_products.length > 0 && (
            <details className="rounded-lg border border-border bg-surface p-4 text-sm">
              <summary className="cursor-pointer font-medium text-text-900">
                Oran ve limit yok — {data.no_data_products.length} ürün
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
