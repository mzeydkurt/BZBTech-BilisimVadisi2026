import { useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import {
  ProductFilters,
  type ProductFilterState,
} from "@/components/products/ProductFilters";
import { ProductTable } from "@/components/products/ProductTable";
import { useBanks } from "@/hooks/useBanks";
import { useProducts } from "@/hooks/useProducts";
import type { ProductQuery } from "@/types/api";

const INITIAL_LIMIT = 50;
const LIMIT_STEP = 50;
const MAX_LIMIT = 100;

function toProductQuery(filters: ProductFilterState, limit: number): ProductQuery {
  return {
    bank_code: filters.bank_code,
    product_type: filters.product_type,
    rate_type: filters.rate_type,
    limit,
  };
}

export function ProductsPage() {
  const [filters, setFilters] = useState<ProductFilterState>({});
  const [limit, setLimit] = useState(INITIAL_LIMIT);

  const { data: banks } = useBanks();
  const query = toProductQuery(filters, limit);
  const { data: products, isLoading, isError, error, refetch } = useProducts(query);

  const handleFiltersChange = (next: ProductFilterState) => {
    setFilters(next);
    setLimit(INITIAL_LIMIT);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Ürün Kataloğu</h1>
        <p className="mt-1 text-sm text-text-500">
          Finansman, katılma hesabı ve diğer ürünler — oranları ve limitleriyle.
        </p>
      </div>

      <ProductFilters banks={banks ?? []} value={filters} onChange={handleFiltersChange} />

      {isLoading && <LoadingState variant="table" />}

      {isError && <ErrorState error={error} onRetry={() => void refetch()} />}

      {!isLoading && !isError && products && products.length === 0 && (
        <EmptyState
          title="Filtrelere uyan ürün bulunamadı"
          description="Farklı bir banka, ürün türü veya oran türü deneyebilirsiniz."
          onClear={() => handleFiltersChange({})}
        />
      )}

      {!isLoading && !isError && products && products.length > 0 && (
        <>
          <ProductTable products={products} />
          {products.length >= limit && limit < MAX_LIMIT && (
            <div className="flex justify-center">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setLimit((prev) => Math.min(prev + LIMIT_STEP, MAX_LIMIT))}
              >
                Daha fazla göster
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
