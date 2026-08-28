import { Link } from "react-router-dom";

import type { ChatAction } from "@/types/api";

const PRODUCT_LABEL: Record<string, string> = {
  tasit_finansmani: "taşıt finansmanı",
  konut_finansmani: "konut finansmanı",
  ihtiyac_finansmani: "ihtiyaç finansmanı",
};

function refineQuery(action: ChatAction, baseQuery: string): string {
  const tip = action.params.product_type;
  if (tip && PRODUCT_LABEL[tip]) {
    const etiket = PRODUCT_LABEL[tip];
    if (baseQuery.toLowerCase().includes(etiket.split(" ")[0]!)) {
      return baseQuery;
    }
    return `${baseQuery} ${etiket}`.trim();
  }
  const asset = action.params.asset_type;
  if (asset) {
    const map: Record<string, string> = {
      tasit: "taşıt",
      konut: "konut",
      ihtiyac: "ihtiyaç",
    };
    return `${baseQuery} ${map[asset] ?? asset}`.trim();
  }
  const term = action.params.term_months;
  if (term) {
    const ek = `${term} ay`;
    // Önceki "12 veya 24 vade" ifadesini tek vadeye indir.
    const temiz = baseQuery
      .replace(/\d{1,3}\s*(?:veya|\/|-|–|—|ile|,)\s*\d{1,3}\s*(?:ay|vade)?/gi, " ")
      .replace(/\b\d{1,3}\s*(?:ay|vade)\b/gi, " ")
      .replace(/\s+/g, " ")
      .trim();
    return `${temiz} ${ek}`.trim();
  }
  const append = action.params.append;
  if (append) {
    return `${baseQuery} ${append}`.trim();
  }
  return baseQuery;
}

function hrefFor(action: ChatAction): string {
  if (!action.path) return "#";
  const params = new URLSearchParams(action.params ?? {});
  // Simülatör bağlantılarında sayıları doldurup hesabı otomatik çalıştır.
  if (action.path.startsWith("/simulator") && !params.has("autorun")) {
    params.set("autorun", "1");
  }
  const qs = params.toString();
  return qs ? `${action.path}?${qs}` : action.path;
}

export function ActionButtons({
  actions,
  baseQuery,
  onRefine,
}: {
  actions: ChatAction[];
  baseQuery: string;
  onRefine?: (query: string) => void;
}) {
  if (!actions.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {actions.map((a, i) => {
        if (a.kind === "refine") {
          return (
            <button
              key={`${a.label}-${i}`}
              type="button"
              className="rounded border border-border bg-neutral-50 px-2.5 py-1 text-xs text-text-900 transition-colors hover:border-brand-500"
              onClick={() => onRefine?.(refineQuery(a, baseQuery))}
            >
              {a.label}
            </button>
          );
        }
        if (a.path) {
          return (
            <Link
              key={`${a.label}-${i}`}
              to={hrefFor(a)}
              className="rounded border border-brand-500/40 bg-teal-100/40 px-2.5 py-1 text-xs font-medium text-brand-700 transition-colors hover:border-brand-500"
            >
              {a.label}
            </Link>
          );
        }
        return null;
      })}
    </div>
  );
}
