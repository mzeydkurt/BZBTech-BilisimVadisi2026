import { ExternalLink } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { StatusBadge } from "@/components/campaigns/StatusBadge";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { Button } from "@/components/ui/button";
import { useCampaign } from "@/hooks/useCampaigns";
import { formatDate, formatDateTime, formatText } from "@/lib/format";
import { taxonomyAxisLabel, taxonomyLabel } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<string, string> = {
  url: "adres yolundan (bankanın verisi)",
  bank_category: "bankanın kendi etiketi",
  merchant: "marka eşleşmesi",
  keyword: "anahtar kelime",
  llm: "yapay zekâ çıkarımı",
};

export function CampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id ? Number(params.id) : null;
  const validId = id !== null && Number.isFinite(id) ? id : null;

  const { data: campaign, isLoading, isError, error, refetch } = useCampaign(validId);

  if (validId === null) {
    return (
      <div className="rounded-lg border border-border bg-surface px-6 py-12 text-center">
        <p className="font-semibold text-text-900">Geçersiz kampanya</p>
        <p className="mt-1 text-sm text-text-500">Adres geçersiz bir kimlik içeriyor.</p>
        <Button asChild variant="secondary" className="mt-4">
          <Link to="/campaigns">Kataloğa dön</Link>
        </Button>
      </div>
    );
  }

  if (isLoading) return <LoadingState variant="cards" />;
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!campaign) return null;

  return (
    <div className="space-y-5">
      <div>
        <Link to="/campaigns" className="text-xs font-medium text-brand-700 hover:underline">
          ← Kampanya kataloğu
        </Link>
        <p className="mt-2 text-sm text-text-500">{campaign.bank_name}</p>
        <h1 className="mt-0.5 text-xl font-semibold text-text-900">{campaign.title}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge
            status={campaign.status}
            datePrecision={campaign.date_precision}
            dateEvidence={campaign.date_evidence_text}
          />
          {campaign.segment && (
            <span className="rounded border border-border px-2 py-0.5 text-xs text-text-500">
              {taxonomyLabel(campaign.segment)}
            </span>
          )}
        </div>
      </div>

      <dl className="grid gap-3 rounded-lg border border-border bg-surface p-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-text-500">Başlangıç</dt>
          <dd className="text-text-900">{formatDate(campaign.start_date)}</dd>
        </div>
        <div>
          <dt className="text-text-500">Bitiş</dt>
          <dd className="text-text-900">{formatDate(campaign.end_date)}</dd>
        </div>
        <div>
          <dt className="text-text-500">İlk görülme</dt>
          <dd className="text-text-900">{formatDateTime(campaign.first_seen_at)}</dd>
        </div>
        <div>
          <dt className="text-text-500">Son görülme</dt>
          <dd className="text-text-900">{formatDateTime(campaign.last_seen_at)}</dd>
        </div>
      </dl>

      {campaign.description && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">Açıklama</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-text-900">
            {campaign.description}
          </p>
        </section>
      )}

      {campaign.conditions_text && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">Koşullar</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-text-900">
            {campaign.conditions_text}
          </p>
        </section>
      )}

      {campaign.exclusions_text && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">İstisnalar</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-text-900">
            {campaign.exclusions_text}
          </p>
        </section>
      )}

      {campaign.categories.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">Sınıflandırma</h2>
          <ul className="mt-2 space-y-2">
            {campaign.categories.map((category) => (
              <li
                key={`${category.axis}-${category.value}`}
                className="rounded border border-border px-3 py-2 text-sm"
              >
                <span className="text-text-500">{taxonomyAxisLabel(category.axis)}</span>
                <span className="ml-2 font-medium text-text-900">
                  {taxonomyLabel(category.value)}
                </span>
                <p className="mt-1 text-xs text-text-500">
                  {SOURCE_LABELS[category.source] ?? category.source}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {campaign.products.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">İlişkili ürünler</h2>
          <ul className="mt-2 space-y-1">
            {campaign.products.map((product) => (
              <li key={product.product_id}>
                <Link
                  to={`/products/${product.product_id}`}
                  className={cn(
                    "text-sm hover:underline",
                    product.match_method === "body" ? "text-text-400" : "text-brand-700",
                  )}
                >
                  {product.product_name}
                  {product.variant_label && ` — ${product.variant_label}`}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {campaign.sub_campaigns.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-text-900">Alt kampanyalar</h2>
          <ul className="mt-2 space-y-1">
            {campaign.sub_campaigns.map((sub) => (
              <li key={sub.id}>
                <Link
                  to={`/campaigns/${sub.id}`}
                  className="text-sm text-brand-700 hover:underline"
                >
                  {sub.title}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-text-900">Kaynak</h2>
        {campaign.source_document && (
          <p className="mt-1 text-xs text-text-500">
            Çekim: {formatDateTime(campaign.source_document.fetched_at)}
            {campaign.source_document.scraper_name
              ? ` · ${formatText(campaign.source_document.scraper_name)}`
              : ""}
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
  );
}
