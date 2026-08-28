import { AlertTriangle, ExternalLink } from "lucide-react";
import { useParams } from "react-router-dom";

import { taxonomyLabel } from "@/lib/taxonomy";
import { BddkLimitsBanner } from "@/components/financing/BddkLimitsBanner";
import { BankLogo } from "@/components/common/BankLogo";
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

  const bindingRates = product.rates.filter(
    (r) =>
      r.rate_source !== "calculator_api" &&
      r.rate_source !== "calculator_playwright" &&
      r.rate_source !== "js_default",
  );
  const probeRates = product.rates.filter(
    (r) =>
      r.rate_source === "calculator_api" ||
      r.rate_source === "calculator_playwright" ||
      r.rate_source === "payment_plan_derived",
  );

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <BankLogo bankCode={product.bank_code} bankName={product.bank_name} size="md" />
          <p className="text-sm font-medium text-text-500">{formatText(product.bank_name)}</p>
        </div>
        <h1 className="mt-0.5 text-xl font-semibold text-text-900">{product.name}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-text-500">
          {product.product_type && (
            <span className="rounded border border-border px-2 py-0.5 text-xs">
              {taxonomyLabel(product.product_type)}
            </span>
          )}
        </div>
        {product.description && (
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-text-900">
            {product.description}
          </p>
        )}
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

      <BddkLimitsBanner limits={product.bddk_limits} />

      <section>
        <h2 className="text-sm font-semibold text-text-900">Oranlar</h2>
        <div className="mt-2">
          <ProductRateTable rates={bindingRates.length > 0 ? bindingRates : product.rates} />
        </div>
      </section>

      {probeRates.length > 0 && bindingRates.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">
            Hesaplayıcı / türetim tahmini
          </h2>
          <p className="mt-1 text-xs text-text-500">
            Bankanın hesaplama aracından veya ödeme planından türetilmiş değerler —
            bağlayıcı teklif değildir.
          </p>
          <div className="mt-2">
            <ProductRateTable rates={probeRates} />
          </div>
        </section>
      )}

      {product.limits.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">Banka LTV / vade matrisi</h2>
          {product.bank_limit_deviations.length > 0 && (
            <ul className="mt-2 space-y-1 rounded-lg border border-warn-600/40 bg-surface px-3 py-2 text-xs text-warn-600">
              {product.bank_limit_deviations.map((d) => (
                <li key={d.limit_id}>{d.message}</li>
              ))}
            </ul>
          )}
          <div className="mt-2">
            <ProductLimitTable limits={product.limits} />
          </div>
        </section>
      )}

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
                {variant.limits.length > 0 && <ProductLimitTable limits={variant.limits} />}
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
