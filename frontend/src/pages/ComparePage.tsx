import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  CampaignCompareForm,
  type CampaignCompareFormState,
  toCampaignCompareRequest,
} from "@/components/compare/CampaignCompareForm";
import { CompareForm, type CompareFormState } from "@/components/compare/CompareForm";
import { RankedCampaignTable } from "@/components/compare/RankedCampaignTable";
import { RankedProductTable } from "@/components/compare/RankedProductTable";
import { WithoutDataSection } from "@/components/compare/WithoutDataSection";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBanks } from "@/hooks/useBanks";
import { useCampaignCompare } from "@/hooks/useCampaignCompare";
import { useProductCompare } from "@/hooks/useProductCompare";
import { downloadCsv } from "@/lib/csv";
import type { ProductRankingRequest, RankedCampaign, RankedProduct } from "@/types/api";

const DEFAULT_COMPARE_FORM: CompareFormState = {
  rate_type: "financing_rate",
  criterion: "en_dusuk_kar_payi",
  product_type: "",
  bank_codes: [],
  term_months: "",
  term_days: "",
  amount_try: "",
  currency: "TRY",
  rate_weight: "50",
  fee_weight: "25",
  term_weight: "25",
};

const DEFAULT_CAMPAIGN_FORM: CampaignCompareFormState = {
  criterion: "en_yuksek_odul",
  product_type: "",
  bank_codes: [],
  only_active: true,
};

function toRequest(form: CompareFormState): ProductRankingRequest {
  const termMonths = form.term_months.trim() ? Number(form.term_months) : null;
  const termDays = form.term_days.trim() ? Number(form.term_days) : null;
  return {
    rate_type: form.rate_type,
    criterion: form.criterion,
    product_type: form.product_type || undefined,
    bank_codes: form.bank_codes.length > 0 ? form.bank_codes : undefined,
    term_months: termMonths && Number.isFinite(termMonths) ? termMonths : undefined,
    term_days: termDays && Number.isFinite(termDays) ? termDays : undefined,
    amount_try: form.amount_try.trim() || undefined,
    currency: form.currency || "TRY",
    weights:
      form.criterion === "en_avantajli"
        ? {
            rate_weight: form.rate_weight,
            fee_weight: form.fee_weight,
            term_weight: form.term_weight,
          }
        : undefined,
    limit: 20,
  };
}

function formFromParams(params: URLSearchParams): CompareFormState {
  const bank = params.get("bank");
  const rateType = params.get("rate_type");
  return {
    ...DEFAULT_COMPARE_FORM,
    bank_codes: bank ? [bank] : [],
    rate_type:
      rateType === "participation_yield" ||
      rateType === "profit_sharing_ratio" ||
      rateType === "financing_rate"
        ? rateType
        : DEFAULT_COMPARE_FORM.rate_type,
    criterion:
      rateType === "participation_yield"
        ? "en_yuksek_getiri"
        : rateType === "profit_sharing_ratio"
          ? "en_yuksek_paylasim_orani"
          : DEFAULT_COMPARE_FORM.criterion,
  };
}

function exportProductsCsv(items: RankedProduct[], filename: string) {
  downloadCsv(
    filename,
    [
      "rank",
      "bank_name",
      "product_name",
      "rate_type",
      "profit_rate_pct",
      "investor_share_pct",
      "allocation_fee_pct",
      "annual_cost_pct",
      "term_months",
      "term_label",
      "effective_date",
      "rate_source",
      "variant_label",
      "account_tier",
      "source_url",
    ],
    items.map((item) => [
      item.rank,
      item.bank_name,
      item.product_name,
      item.rate_type,
      item.profit_rate_pct,
      item.investor_share_pct,
      item.allocation_fee_pct,
      item.annual_cost_pct,
      item.term_months,
      item.term_label,
      item.effective_date,
      item.rate_source,
      item.variant_label,
      item.account_tier,
      item.source_url,
    ]),
  );
}

function exportCampaignsCsv(items: RankedCampaign[], filename: string) {
  downloadCsv(
    filename,
    [
      "rank",
      "bank_name",
      "title",
      "status",
      "reward_amount_try",
      "cashback_pct",
      "discount_pct",
      "installment_count",
      "profit_rate_pct",
      "term_months_max",
      "end_date",
      "source_url",
    ],
    items.map((item) => [
      item.rank,
      item.bank_name,
      item.title,
      item.status,
      item.reward_amount_try,
      item.cashback_pct,
      item.discount_pct,
      item.installment_count,
      item.profit_rate_pct,
      item.term_months_max,
      item.end_date,
      item.source_url,
    ]),
  );
}

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const [form, setForm] = useState<CompareFormState>(() => formFromParams(searchParams));
  const [campaignForm, setCampaignForm] =
    useState<CampaignCompareFormState>(DEFAULT_CAMPAIGN_FORM);
  const { data: banks } = useBanks();
  const productMutation = useProductCompare();
  const campaignMutation = useCampaignCompare();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Karşılaştırma</h1>
        <p className="mt-1 text-sm text-text-500">
          Ürün oranları ve kampanya ödül / iade ölçütlerine göre sıralama.
        </p>
      </div>

      <Tabs defaultValue="products">
        <TabsList>
          <TabsTrigger value="products">Ürünler</TabsTrigger>
          <TabsTrigger value="campaigns">Kampanyalar</TabsTrigger>
        </TabsList>

        <TabsContent value="products" className="space-y-4">
          <CompareForm
            value={form}
            onChange={setForm}
            onSubmit={() => productMutation.mutate(toRequest(form))}
            banks={banks ?? []}
            isPending={productMutation.isPending}
          />

          {productMutation.isPending && <LoadingState variant="table" />}

          {productMutation.isError && (
            <ErrorState error={productMutation.error} title="Karşılaştırma yapılamadı" />
          )}

          {productMutation.isSuccess && (
            <div className="space-y-4">
              {productMutation.data.winner && (
                <div className="rounded-lg border border-brand-700/40 bg-teal-100/50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-brand-900">
                    Kazanan
                  </p>
                  <p className="mt-1 text-sm text-text-900">
                    {productMutation.data.winner_reason}
                  </p>
                </div>
              )}

              {(productMutation.data.comparability_warnings?.length ?? 0) > 0 && (
                <div className="rounded-lg border border-warn-600/40 bg-surface px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-warn-600">
                    Karşılaştırılabilirlik uyarıları
                  </p>
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-text-900">
                    {productMutation.data.comparability_warnings!.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              {productMutation.data.ranked.length > 0 ? (
                <>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        exportProductsCsv(
                          productMutation.data.ranked,
                          `urun-karsilastirma-${productMutation.data.criterion}.csv`,
                        )
                      }
                    >
                      CSV indir
                    </Button>
                  </div>
                  <RankedProductTable
                    items={productMutation.data.ranked}
                    winnerId={productMutation.data.winner?.product_id}
                    rateType={productMutation.data.rate_type}
                  />
                </>
              ) : (
                <p className="text-sm text-text-500">{productMutation.data.note}</p>
              )}

              <WithoutDataSection items={productMutation.data.without_data} />
            </div>
          )}
        </TabsContent>

        <TabsContent value="campaigns" className="space-y-4">
          <CampaignCompareForm
            value={campaignForm}
            onChange={setCampaignForm}
            onSubmit={() =>
              campaignMutation.mutate(toCampaignCompareRequest(campaignForm))
            }
            banks={banks ?? []}
            isPending={campaignMutation.isPending}
          />

          {campaignMutation.isPending && <LoadingState variant="table" />}

          {campaignMutation.isError && (
            <ErrorState error={campaignMutation.error} title="Kampanya karşılaştırması yapılamadı" />
          )}

          {campaignMutation.isSuccess && (
            <div className="space-y-4">
              {campaignMutation.data.winner && (
                <div className="rounded-lg border border-brand-700/40 bg-teal-100/50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-brand-900">
                    Kazanan
                  </p>
                  <p className="mt-1 text-sm text-text-900">
                    {campaignMutation.data.winner_reason}
                  </p>
                </div>
              )}

              {campaignMutation.data.ranked.length > 0 ? (
                <>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        exportCampaignsCsv(
                          campaignMutation.data.ranked,
                          `kampanya-karsilastirma-${campaignMutation.data.criterion}.csv`,
                        )
                      }
                    >
                      CSV indir
                    </Button>
                  </div>
                  <RankedCampaignTable
                    items={campaignMutation.data.ranked}
                    winnerId={campaignMutation.data.winner?.campaign_id}
                    criterion={campaignMutation.data.criterion}
                  />
                </>
              ) : (
                <p className="text-sm text-text-500">{campaignMutation.data.note}</p>
              )}

              {campaignMutation.data.without_data.length > 0 && (
                <div className="rounded-lg border border-dashed border-border bg-neutral-50 p-4">
                  <h3 className="text-sm font-semibold text-text-500">
                    Ölçüt alanı boş olduğu için sıralanamayanlar
                  </h3>
                  <ul className="mt-2 space-y-1">
                    {campaignMutation.data.without_data.map((item) => (
                      <li key={item.campaign_id} className="text-sm text-text-500">
                        <span className="font-medium text-text-900">{item.title}</span>
                        {item.missing_reason ? ` — ${item.missing_reason}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
