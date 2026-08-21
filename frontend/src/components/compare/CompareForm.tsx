import { taxonomyLabel } from "@/lib/taxonomy";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CRITERIA_LABELS, getValidCriteria } from "@/lib/compareRules";
import { cn } from "@/lib/utils";
import type { Bank, ComparableRateType, ProductRankingRequest } from "@/types/api";

const RATE_TYPE_OPTIONS: { value: ComparableRateType; label: string }[] = [
  { value: "financing_rate", label: "Finansman maliyeti" },
  { value: "participation_yield", label: "Katılma getirisi" },
  { value: "profit_sharing_ratio", label: "Katılımcı payı" },
];

export interface CompareFormState {
  rate_type: ComparableRateType;
  criterion: ProductRankingRequest["criterion"];
  product_type: string;
  bank_codes: string[];
  rate_weight: string;
  fee_weight: string;
  term_weight: string;
}

interface CompareFormProps {
  value: CompareFormState;
  onChange: (next: CompareFormState) => void;
  onSubmit: () => void;
  banks: Bank[];
  isPending: boolean;
}

export function CompareForm({ value, onChange, onSubmit, banks, isPending }: CompareFormProps) {
  const validCriteria = getValidCriteria(value.rate_type);

  const handleRateTypeChange = (rateType: ComparableRateType) => {
    const nextCriteria = getValidCriteria(rateType);
    onChange({
      ...value,
      rate_type: rateType,
      criterion: nextCriteria.includes(value.criterion) ? value.criterion : nextCriteria[0] ?? value.criterion,
    });
  };

  const toggleBank = (code: string) => {
    const next = value.bank_codes.includes(code)
      ? value.bank_codes.filter((item) => item !== code)
      : [...value.bank_codes, code];
    onChange({ ...value, bank_codes: next });
  };

  return (
    <form
      className="space-y-4 rounded-lg border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="flex flex-wrap gap-3">
        <div className="w-56">
          <label htmlFor="compare-rate-type" className="mb-1 block text-sm text-text-500">
            Oran Türü
          </label>
          <Select value={value.rate_type} onValueChange={(next) => handleRateTypeChange(next as ComparableRateType)}>
            <SelectTrigger id="compare-rate-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RATE_TYPE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-64">
          <label htmlFor="compare-criterion" className="mb-1 block text-sm text-text-500">
            Ölçüt
          </label>
          <Select
            value={value.criterion}
            onValueChange={(next) => onChange({ ...value, criterion: next as CompareFormState["criterion"] })}
          >
            <SelectTrigger id="compare-criterion">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {validCriteria.map((criterion) => (
                <SelectItem key={criterion} value={criterion}>
                  {CRITERIA_LABELS[criterion]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-56">
          <label htmlFor="compare-product-type" className="mb-1 block text-sm text-text-500">
            Ürün Türü (opsiyonel)
          </label>
          <Input
            id="compare-product-type"
            value={value.product_type}
            onChange={(event) => onChange({ ...value, product_type: event.target.value })}
            placeholder="ör. tasit_finansmani"
          />
          {value.product_type && (
            <p className="mt-1 text-xs text-text-500">{taxonomyLabel(value.product_type)}</p>
          )}
        </div>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm text-text-500">Bankalar (opsiyonel, boşsa tümü)</legend>
        <div className="flex flex-wrap gap-2">
          {banks.map((bank) => {
            const selected = value.bank_codes.includes(bank.code);
            return (
              <button
                key={bank.code}
                type="button"
                onClick={() => toggleBank(bank.code)}
                aria-pressed={selected}
                className={cn(
                  "rounded-sm border px-2.5 py-1 text-sm transition-colors duration-150",
                  selected
                    ? "border-brand-700 bg-teal-100 text-brand-900"
                    : "border-border bg-surface text-text-900 hover:border-text-500",
                )}
              >
                {bank.name}
              </button>
            );
          })}
        </div>
      </fieldset>

      {/* ⚠️ Ağırlık slider'ları yalnızca "en_avantajli" ölçütünde anlamlıdır;
          diğerlerinde gizlenir, devre dışı gösterip etkisiz kontrol vaat edilmez. */}
      {value.criterion === "en_avantajli" && (
        <fieldset className="grid gap-3 sm:grid-cols-3">
          <legend className="mb-1 text-sm text-text-500 sm:col-span-3">Ağırlıklar (toplam 100)</legend>
          <WeightInput
            label="Oran"
            value={value.rate_weight}
            onChange={(next) => onChange({ ...value, rate_weight: next })}
          />
          <WeightInput
            label="Masraf"
            value={value.fee_weight}
            onChange={(next) => onChange({ ...value, fee_weight: next })}
          />
          <WeightInput
            label="Vade"
            value={value.term_weight}
            onChange={(next) => onChange({ ...value, term_weight: next })}
          />
        </fieldset>
      )}

      <Button type="submit" disabled={isPending}>
        {isPending ? "Karşılaştırılıyor…" : "Karşılaştır"}
      </Button>
    </form>
  );
}

function WeightInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 flex items-center justify-between text-xs text-text-500">
        {label}
        <span className="tabular font-medium text-text-900">{value}</span>
      </label>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full accent-brand-700"
      />
    </div>
  );
}
