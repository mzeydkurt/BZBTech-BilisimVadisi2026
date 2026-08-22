import * as Dialog from "@radix-ui/react-dialog";
import { ExternalLink, X } from "lucide-react";

import { StatusBadge } from "@/components/campaigns/StatusBadge";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { formatDateTime, formatText } from "@/lib/format";
import { taxonomyAxisLabel, taxonomyLabel } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import { useCampaign } from "@/hooks/useCampaigns";
import type { CampaignCategory } from "@/types/api";

interface EvidenceDrawerProps {
  /** `null` iken çekmece kapalıdır. */
  campaignId: number | null;
  onClose: () => void;
}

const SOURCE_LABELS: Record<string, string> = {
  url: "adres yolundan (bankanın verisi)",
  bank_category: "bankanın kendi etiketi",
  merchant: "marka eşleşmesi",
  keyword: "anahtar kelime",
  llm: "yapay zekâ çıkarımı",
};

/**
 * Bir kampanyanın kanıt izini gösteren sağdan kayan çekmece.
 *
 * ⚠️ Kendi verisini kendi çeker (`useCampaign`): liste sayfası yalnızca
 * `CampaignListItem` tutar, `conditions_text`/`source_document` gibi kanıt
 * alanları yalnızca detay uçta gelir.
 */
export function EvidenceDrawer({ campaignId, onClose }: EvidenceDrawerProps) {
  const open = campaignId !== null;
  const { data: campaign, isLoading, isError, error, refetch } = useCampaign(campaignId);

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-text-900/30 transition-opacity duration-150 data-[state=closed]:opacity-0 data-[state=open]:opacity-100" />
        <Dialog.Content
          className={cn(
            "fixed inset-y-0 right-0 z-50 flex h-full w-full max-w-md flex-col overflow-y-auto",
            "border-l border-border bg-surface shadow-xl transition-transform duration-150",
            "data-[state=closed]:translate-x-full data-[state=open]:translate-x-0",
          )}
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <Dialog.Title className="text-sm font-semibold text-text-900">
              Kampanya Kanıtı
            </Dialog.Title>
            <Dialog.Close
              className="rounded-sm p-1 text-text-500 transition-colors duration-150 hover:text-text-900"
              aria-label="Çekmeceyi kapat"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          <div className="flex-1 px-4 py-4">
            {isLoading && <LoadingState variant="cards" />}

            {isError && <ErrorState error={error} onRetry={() => void refetch()} />}

            {!isLoading && !isError && campaign && (
              <div className="space-y-5">
                <div>
                  <p className="text-xs text-text-500">{campaign.bank_name}</p>
                  <h3 className="mt-0.5 text-base font-semibold text-text-900">
                    {campaign.title}
                  </h3>
                  <div className="mt-2">
                    <StatusBadge
                      status={campaign.status}
                      datePrecision={campaign.date_precision}
                      dateEvidence={campaign.date_evidence_text}
                    />
                  </div>
                </div>

                <section>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                    Kanal ve banka etiketi
                  </h4>
                  <dl className="mt-2 space-y-2 text-sm">
                    <div className="flex gap-2">
                      <dt className="w-28 shrink-0 text-text-500">Segment</dt>
                      <dd className="text-text-900">
                        {campaign.segment ? taxonomyLabel(campaign.segment) : "—"}
                        {campaign.segment && (
                          <span className="ml-1 text-xs text-text-500">
                            (scraper / sınıflandırma)
                          </span>
                        )}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-28 shrink-0 text-text-500">Banka kategorisi</dt>
                      <dd className="text-text-900">
                        {campaign.bank_category
                          ? formatText(campaign.bank_category)
                          : "Kaynakta yok"}
                      </dd>
                    </div>
                  </dl>
                </section>

                {campaign.description && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                      Açıklama (kaynaktan birebir)
                    </h4>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-text-900">
                      {campaign.description}
                    </p>
                  </section>
                )}

                <section>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                    Tarih Kanıtı
                  </h4>
                  {campaign.date_evidence_text ? (
                    <p className="mt-1 text-sm text-text-900">
                      “{campaign.date_evidence_text}”
                      {campaign.date_evidence_source && (
                        <span className="text-text-500">
                          {" "}
                          — kaynak: {formatText(campaign.date_evidence_source)}
                        </span>
                      )}
                    </p>
                  ) : (
                    <p className="mt-1 text-sm text-text-500">
                      Kaynak sayfada tarihe dair bir ifade bulunamadı.
                    </p>
                  )}
                </section>

                <section>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                    Sınıflandırma (nasıl anladık)
                  </h4>
                  {campaign.categories.length === 0 ? (
                    <p className="mt-1 text-sm text-text-500">Sınıflandırma henüz çalıştırılmadı.</p>
                  ) : (
                    <ul className="mt-2 space-y-3">
                      {campaign.categories.map((category) => (
                        <ClassificationEvidenceRow
                          key={`${category.axis}-${category.value}`}
                          category={category}
                        />
                      ))}
                    </ul>
                  )}
                </section>

                {campaign.conditions_text && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                      Koşullar
                    </h4>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-text-900">
                      {campaign.conditions_text}
                    </p>
                  </section>
                )}

                {campaign.exclusions_text && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                      İstisnalar
                    </h4>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-text-900">
                      {campaign.exclusions_text}
                    </p>
                  </section>
                )}

                {campaign.products.length > 0 && (
                  <section>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                      İlişkili Ürünler
                    </h4>
                    <ul className="mt-1 space-y-1">
                      {campaign.products.map((product) => (
                        <li
                          key={product.product_id}
                          className={cn(
                            "text-sm",
                            product.match_method === "body" ? "text-text-400" : "text-text-900",
                          )}
                        >
                          {product.product_name}
                          {product.variant_label && ` — ${product.variant_label}`}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <section className="border-t border-border pt-3">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-text-500">
                    Kaynak
                  </h4>
                  {campaign.source_document && (
                    <p className="mt-1 text-xs text-text-500">
                      Çekim zamanı: {formatDateTime(campaign.source_document.fetched_at)}
                    </p>
                  )}
                  <a
                    href={campaign.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:text-brand-900"
                  >
                    Bankanın sayfasında gör
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  </a>
                </section>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ClassificationEvidenceRow({ category }: { category: CampaignCategory }) {
  const weak = Number(category.confidence) < 0.5;
  return (
    <li
      className={cn(
        "rounded border px-3 py-2",
        weak ? "border-dashed border-border" : "border-border bg-surface-50",
      )}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
        <span className="text-text-500">{taxonomyAxisLabel(category.axis)}</span>
        <span className="font-medium text-text-900">{taxonomyLabel(category.value)}</span>
      </div>
      <p className="mt-1 text-xs text-text-500">
        {SOURCE_LABELS[category.source] ?? category.source}
        {" · güven "}
        {Number(category.confidence).toFixed(2)}
      </p>
      {category.evidence ? (
        <p className="mt-1 text-sm text-text-900">“{category.evidence}”</p>
      ) : (
        <p className="mt-1 text-sm text-text-500">
          {category.value === "genel"
            ? "Sektör sinyali bulunamadı; düşük güvenli genel etiket."
            : "Kanıt metni yok."}
        </p>
      )}
    </li>
  );
}
