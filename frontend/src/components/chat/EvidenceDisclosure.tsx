import { ChevronRight, ExternalLink } from "lucide-react";
import { useState } from "react";

import { StatusBadge } from "@/components/campaigns/StatusBadge";
import { formatNumber, parseDecimal } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CampaignStatus, ChatResultItem } from "@/types/api";

/** `compute_status()`'ın döndürdüğü dört değer. */
const STATUSES = ["active", "upcoming", "expired", "unknown"] as const;

/**
 * Backend'den gelen durumu daraltır.
 *
 * ⚠️ VARSAYILAN `unknown`, `expired` DEĞİL. Tanınmayan bir değeri "süresi
 * dolmuş" göstermek, hâlâ geçerli bir kampanyayı bitmiş gibi sunar; `unknown`
 * "bilmiyoruz" der ve arayüzde görsel olarak da ayrıdır (CLAUDE.md).
 */
function asStatus(value: string): CampaignStatus {
  return (STATUSES as readonly string[]).includes(value) ? (value as CampaignStatus) : "unknown";
}

/** Decimal dizesini birimiyle yazar. */
function metricText(value: string, unit: string): string {
  const sayi = parseDecimal(value);
  if (sayi === null) {
    return "—";
  }
  return unit === "%" ? `%${formatNumber(sayi)}` : `${formatNumber(sayi)}${unit}`;
}

/**
 * Yanıtın dayandığı kanıt metinleri — katlanabilir.
 *
 * ⚠️ KANIT METNİ ARAYÜZDE BULUNMAK ZORUNDA. `top_matches` kartları yalnızca
 * başlık ve bağlantı gösteriyor; yanıttaki bir sayının hangi cümleden geldiği
 * bankanın sayfasına gidilmeden görülemiyordu. Kaynağı bir tık uzakta olan bir
 * finansal iddia ile kaynağı olmayan bir iddia arasındaki fark budur.
 *
 * ⚠️ VARSAYILAN KAPALI. Sohbet akışında her turda beş kart açık durursa
 * konuşma okunamaz hâle gelir; kapalı ama TEK TIKLA erişilebilir.
 */
export function EvidenceDisclosure({ results }: { results: ChatResultItem[] }) {
  const [acik, setAcik] = useState(false);

  if (results.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        type="button"
        onClick={() => setAcik((onceki) => !onceki)}
        aria-expanded={acik}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-medium text-text-700 transition-colors hover:bg-neutral-50"
      >
        <ChevronRight
          className={cn("h-3.5 w-3.5 transition-transform", acik && "rotate-90")}
          aria-hidden="true"
        />
        Yanıtın dayandığı kanıt ({results.length} kayıt)
      </button>

      {acik && (
        <ul className="divide-y divide-border border-t border-border">
          {results.map((sonuc) => (
            <li key={sonuc.campaign_id} className="px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-text-500">{sonuc.bank_name}</span>
                <StatusBadge status={asStatus(sonuc.status)} />
                <a
                  href={sonuc.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-900"
                >
                  Bankanın sayfası
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </a>
              </div>

              <p className="mt-0.5 text-sm font-medium text-text-900">{sonuc.title}</p>

              <p className="mt-1.5 whitespace-pre-wrap border-l-2 border-border pl-2.5 text-xs leading-relaxed text-text-700">
                {sonuc.card_text}
              </p>

              {sonuc.metrics.length > 0 && (
                <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                  {sonuc.metrics.map((metrik) => (
                    <div key={metrik.field} className="flex items-baseline gap-1">
                      <dt className="text-xs text-text-500">{metrik.label}:</dt>
                      <dd className="text-xs tabular-nums text-text-900">
                        {metricText(metrik.value, metrik.unit)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}

              {/* Bu kaydın neden döndüğü; gizlemek "sihir" izlenimi verir. */}
              <p className="mt-1.5 text-xs text-text-500">
                {sonuc.channels.length === 0
                  ? "Yalnızca yapısal süzgeçle getirildi (metin eşleşmesi yok)."
                  : `Getiren kanal: ${sonuc.channels
                      .map((kanal) => (kanal === "lexical" ? "sözcüksel" : "anlamsal"))
                      .join(" + ")}`}
                {sonuc.matched_terms.length > 0 &&
                  ` · eşleşen terimler: ${sonuc.matched_terms.slice(0, 6).join(", ")}`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
