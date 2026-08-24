import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { CompareForm, type CompareFormState } from "@/components/compare/CompareForm";
import { RankedProductTable } from "@/components/compare/RankedProductTable";
import { WithoutDataSection } from "@/components/compare/WithoutDataSection";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { useBanks } from "@/hooks/useBanks";
import { useProductCompare } from "@/hooks/useProductCompare";
import type { ProductRankingRequest } from "@/types/api";

const DEFAULT_COMPARE_FORM: CompareFormState = {
  rate_type: "financing_rate",
  criterion: "en_dusuk_kar_payi",
  product_type: "",
  bank_codes: [],
  rate_weight: "50",
  fee_weight: "25",
  term_weight: "25",
};

function toRequest(form: CompareFormState): ProductRankingRequest {
  return {
    rate_type: form.rate_type,
    criterion: form.criterion,
    product_type: form.product_type || undefined,
    bank_codes: form.bank_codes.length > 0 ? form.bank_codes : undefined,
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

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const [form, setForm] = useState<CompareFormState>(() => formFromParams(searchParams));
  const { data: banks } = useBanks();
  const mutation = useProductCompare();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Ürün Karşılaştırma</h1>
        <p className="mt-1 text-sm text-text-500">
          Seçili ölçüte göre bankalar arası ürün sıralaması.
        </p>
      </div>

      <CompareForm
        value={form}
        onChange={setForm}
        onSubmit={() => mutation.mutate(toRequest(form))}
        banks={banks ?? []}
        isPending={mutation.isPending}
      />

      {mutation.isPending && <LoadingState variant="table" />}

      {mutation.isError && (
        <ErrorState error={mutation.error} title="Karşılaştırma yapılamadı" />
      )}

      {mutation.isSuccess && (
        <div className="space-y-4">
          {mutation.data.winner && (
            <div className="rounded-lg border border-brand-700/40 bg-teal-100/50 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-900">
                Kazanan
              </p>
              {/* ⚠️ `winner_reason` backend'den birebir gösterilir, yeniden yazılmaz. */}
              <p className="mt-1 text-sm text-text-900">{mutation.data.winner_reason}</p>
            </div>
          )}

          {mutation.data.ranked.length > 0 ? (
            <RankedProductTable
              items={mutation.data.ranked}
              winnerId={mutation.data.winner?.product_id}
            />
          ) : (
            <p className="text-sm text-text-500">{mutation.data.note}</p>
          )}

          <WithoutDataSection items={mutation.data.without_data} />
        </div>
      )}
    </div>
  );
}
