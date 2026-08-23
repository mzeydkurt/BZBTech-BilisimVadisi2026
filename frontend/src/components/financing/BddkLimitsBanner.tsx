import { formatCurrencyTRY, formatMonths, formatPercent } from "@/lib/format";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { BddkCanonicalLimitsOut } from "@/types/api";

const FAMILY_LABELS: Record<string, string> = {
  ihtiyac: "İhtiyaç",
  konut: "Konut",
  tasit: "Taşıt",
};

const FAMILY_ORDER = ["ihtiyac", "konut", "tasit"] as const;

function bandDetail(band: BddkCanonicalLimitsOut["bands"][number]) {
  if (band.rates) {
    return Object.entries(band.rates)
      .map(([k, v]) => `${k} ${formatPercent(v, { decimals: 1 })}`)
      .join(" · ");
  }
  if (band.max_ratio_pct) {
    return formatPercent(band.max_ratio_pct, { decimals: 0 });
  }
  if (band.amount_max || band.amount_min) {
    return `${formatCurrencyTRY(band.amount_min)} – ${formatCurrencyTRY(band.amount_max)}`;
  }
  return "—";
}

function LimitsTable({ limits }: { limits: BddkCanonicalLimitsOut }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[24rem] text-left text-xs">
        <thead>
          <tr className="border-b border-border text-text-500">
            <th className="py-1.5 pr-2 font-medium">Bant</th>
            <th className="py-1.5 pr-2 text-right font-medium">Azami vade</th>
            <th className="py-1.5 text-right font-medium">Azami oran</th>
          </tr>
        </thead>
        <tbody>
          {limits.bands.map((band) => (
            <tr key={band.label} className="border-b border-border/50 last:border-0">
              <td className="py-1.5 pr-2 text-text-900">{band.label}</td>
              <td className="tabular py-1.5 pr-2 text-right text-text-500">
                {formatMonths(band.max_term_months ?? limits.max_term_months)}
              </td>
              <td className="tabular py-1.5 text-right text-text-900">
                {bandDetail(band)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LimitsFooter({ limits }: { limits: BddkCanonicalLimitsOut }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-500">
      <span>
        Karar {limits.decision_no}
        {limits.as_of ? ` · ${limits.as_of}` : ""}
      </span>
      <a
        href={limits.source_url}
        target="_blank"
        rel="noreferrer noopener"
        className="font-medium text-brand-700 hover:text-brand-900"
      >
        Dayanak
      </a>
      {limits.second_home_note && (
        <span className="basis-full text-text-500">{limits.second_home_note}</span>
      )}
    </div>
  );
}

/** Ürün detayı: tek aile, tablo açık. */
export function BddkLimitsBanner({
  limits,
}: {
  limits: BddkCanonicalLimitsOut | null | undefined;
}) {
  if (!limits) return null;

  const title = FAMILY_LABELS[limits.family] ?? limits.family;

  return (
    <section className="rounded-lg border border-border bg-surface px-4 py-3">
      <h2 className="text-sm font-semibold text-text-900">BDDK tavanı — {title}</h2>
      <p className="mt-0.5 text-xs text-text-500">
        Yasal üst sınır. Bankanın kendi LTV tablosu aşağıda ayrı gösterilir.
      </p>
      <div className="mt-3">
        <LimitsTable limits={limits} />
      </div>
      <LimitsFooter limits={limits} />
    </section>
  );
}

/** Liste sayfası: tek satır özet, tıklanınca sekmeli tablo. */
export function BddkLimitsPanel({
  byFamily,
  activeFamily,
}: {
  byFamily: Record<string, BddkCanonicalLimitsOut>;
  /** Filtredeki ürüne göre varsayılan sekme */
  activeFamily?: string | null;
}) {
  const families = FAMILY_ORDER.filter((f) => byFamily[f]);
  if (families.length === 0) return null;

  const defaultTab =
    activeFamily && byFamily[activeFamily] ? activeFamily : families[0];

  return (
    <details className="rounded-lg border border-border bg-surface text-sm">
      <summary className="cursor-pointer list-none px-4 py-2.5 font-medium text-text-900 marker:content-none [&::-webkit-details-marker]:hidden">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span>BDDK yasal tavanlar</span>
          <span className="font-normal text-text-500">
            {families.map((f) => FAMILY_LABELS[f] ?? f).join(" · ")}
          </span>
          <span className="ml-auto text-xs font-normal text-text-500">Detay</span>
        </span>
      </summary>
      <div className="border-t border-border px-4 pb-3 pt-2">
        <Tabs defaultValue={defaultTab}>
          <TabsList>
            {families.map((f) => (
              <TabsTrigger key={f} value={f}>
                {FAMILY_LABELS[f] ?? f}
              </TabsTrigger>
            ))}
          </TabsList>
          {families.map((f) => {
            const limits = byFamily[f];
            if (!limits) return null;
            return (
              <TabsContent key={f} value={f} className="mt-3">
                <LimitsTable limits={limits} />
                <LimitsFooter limits={limits} />
              </TabsContent>
            );
          })}
        </Tabs>
      </div>
    </details>
  );
}
