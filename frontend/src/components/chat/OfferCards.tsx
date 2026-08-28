import { Link } from "react-router-dom";

import { formatCurrencyTRY, formatPercent } from "@/lib/format";
import type { ChatOfferItem } from "@/types/api";

function actionHref(offer: ChatOfferItem): string {
  const a = offer.action;
  if (!a?.path) {
    return offer.product_id ? `/products/${offer.product_id}` : "/simulator";
  }
  const params = new URLSearchParams(a.params ?? {});
  if (!params.has("autorun")) params.set("autorun", "1");
  const qs = params.toString();
  return qs ? `${a.path}?${qs}` : a.path;
}

function isYieldOffer(offer: ChatOfferItem): boolean {
  return (
    offer.product_type === "birikim_katilma_hesabi" ||
    offer.action?.params?.tab === "yield"
  );
}

export function OfferCards({ offers }: { offers: ChatOfferItem[] }) {
  if (!offers.length) return null;
  const cols =
    offers.length === 1
      ? "sm:grid-cols-1"
      : offers.length === 2
        ? "sm:grid-cols-2"
        : "sm:grid-cols-3";
  return (
    <div className={`mt-3 grid grid-cols-1 gap-2 ${cols}`}>
      {offers.map((o) => {
        const yieldLike = isYieldOffer(o);
        return (
          <Link
            key={`${o.bank_code}-${o.product_id ?? o.product_name}`}
            to={actionHref(o)}
            className="flex h-full min-h-[8rem] flex-col rounded-lg border border-border bg-surface px-3 py-2.5 transition-colors hover:border-brand-500"
          >
            <p className="text-[11px] text-text-500">{o.bank_name}</p>
            <p className="mt-0.5 text-sm font-medium leading-snug text-text-900 line-clamp-2">
              {o.product_name ?? o.bank_name}
            </p>

            {yieldLike ? (
              <div className="mt-2 space-y-0.5">
                {o.total_cost_try != null && (
                  <p className="text-base font-semibold text-brand-700">
                    {formatCurrencyTRY(o.total_cost_try)}{" "}
                    <span className="text-xs font-normal text-text-500">net getiri</span>
                  </p>
                )}
                {o.profit_rate_pct != null && (
                  <p className="text-xs text-text-500">
                    Yıllık {formatPercent(o.profit_rate_pct)}
                  </p>
                )}
              </div>
            ) : (
              <div className="mt-2 space-y-0.5">
                {o.monthly_payment_try != null && (
                  <p className="text-base font-semibold text-brand-700">
                    {formatCurrencyTRY(o.monthly_payment_try)}{" "}
                    <span className="text-xs font-normal text-text-500">/ ay</span>
                  </p>
                )}
                {o.total_cost_try != null && (
                  <p className="text-xs text-text-500">
                    Toplam {formatCurrencyTRY(o.total_cost_try)}
                    {o.profit_rate_pct != null
                      ? ` · Kâr payı ${formatPercent(o.profit_rate_pct)}`
                      : ""}
                  </p>
                )}
              </div>
            )}

            {o.summary && o.monthly_payment_try == null && o.total_cost_try == null && (
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-500 line-clamp-3">
                {o.summary}
              </p>
            )}

            <p className="mt-auto pt-2 text-[11px] font-medium text-brand-700">
              {o.action?.label ?? "Simülatörde hesapla"} →
            </p>
          </Link>
        );
      })}
    </div>
  );
}
