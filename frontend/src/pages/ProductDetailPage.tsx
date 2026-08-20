import { AlertTriangle, ExternalLink } from "lucide-react";
import { useParams } from "react-router-dom";

import { taxonomyLabel } from "@/lib/taxonomy";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { ProductLimitTable } from "@/components/products/ProductLimitTable";
import { ProductRateTable } from "@/components/products/ProductRateTable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useProduct } from "@/hooks/useProducts";
import { formatDateTime, formatText } from "@/lib/format";

export function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id ? Number(params.id) : null;

  const { data: product, isLoading, isError, error, refetch } = useProduct(id);

  if (isLoading) return <LoadingState variant="cards" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!product) return null;

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-text-500">{formatText(product.bank_name)}</p>
        <h1 className="mt-0.5 text-xl font-semibold text-text-900">{product.name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-text-500">
          {product.product_type && (
            <span className="rounded border border-border px-2 py-0.5 text-xs">
              {taxonomyLabel(product.product_type)}
            </span>
          )}
          {product.description && <span>{product.description}</span>}
        </div>
      </div>

      {!product.is_binding && (
        <div className="flex items-start gap-2 rounded-lg border border-warn-600/40 bg-surface px-4 py-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn-600" aria-hidden="true" />
          <p className="text-text-900">
            {formatText(
              product.non_binding_notice,
              "Bu değerler bankanın hesaplayıcısına sorgu atılmadan, yapısal form alanlarından elde edilmiştir; bağlayıcı bir teklif değildir.",
            )}
          </p>
        </div>
      )}

      <section>
        <h2 className="text-sm font-semibold text-text-900">Oranlar</h2>
        <div className="mt-2">
          <ProductRateTable rates={product.rates} />
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-text-900">BDDK Limitleri</h2>
        <div className="mt-2">
          <ProductLimitTable limits={product.limits} />
        </div>
      </section>

      {product.variants.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">Varyantlar</h2>
          <p className="mt-1 text-xs text-text-500">
            Aynı ürünün farklı koşullara bağlı oranları — sekmeler arasında geçiş yaparak
            karşılaştırın.
          </p>
          <Tabs defaultValue={String(product.variants[0]?.id ?? "")} className="mt-3">
            <TabsList>
              {product.variants.map((variant) => (
                <TabsTrigger key={variant.id} value={String(variant.id)}>
                  {formatText(variant.variant_label, variant.name)}
                </TabsTrigger>
              ))}
            </TabsList>
            {product.variants.map((variant) => (
              <TabsContent key={variant.id} value={String(variant.id)} className="space-y-4">
                <ProductRateTable rates={variant.rates} />
                <ProductLimitTable limits={variant.limits} />
              </TabsContent>
            ))}
          </Tabs>
        </section>
      )}

      <section className="border-t border-border pt-4">
        {product.source_fetched_at && (
          <p className="text-xs text-text-500">
            Çekim zamanı: {formatDateTime(product.source_fetched_at)}
          </p>
        )}
        {product.source_url ? (
          <a
            href={product.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="mt-1 inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:text-brand-900"
          >
            Bankanın sayfasında gör
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        ) : (
          <p className="mt-1 text-sm text-text-500">Kaynak sayfa adresi kayıtlı değil.</p>
        )}
      </section>
    </div>
  );
}
