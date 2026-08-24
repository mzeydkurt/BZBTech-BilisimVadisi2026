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
import { cn } from "@/lib/utils";
import type { Bank } from "@/types/api";

const PRODUCT_TYPES = ["tasit_finansmani", "konut_finansmani", "ihtiyac_finansmani"] as const;

export interface FinancingFormState {
  amount_try: string;
  term_months: string;
  product_type: (typeof PRODUCT_TYPES)[number];
  bank_codes: string[];
}

interface FinancingFormProps {
  value: FinancingFormState;
  onChange: (next: FinancingFormState) => void;
  onSubmit: () => void;
  isPending: boolean;
  banks?: Bank[];
}

export function FinancingForm({
  value,
  onChange,
  onSubmit,
  isPending,
  banks = [],
}: FinancingFormProps) {
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
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-48">
          <label htmlFor="fin-amount" className="mb-1 block text-sm text-text-500">
            Tutar (TL)
          </label>
          <Input
            id="fin-amount"
            inputMode="numeric"
            value={value.amount_try}
            onChange={(event) => onChange({ ...value, amount_try: event.target.value })}
          />
        </div>

        <div className="w-32">
          <label htmlFor="fin-term" className="mb-1 block text-sm text-text-500">
            Vade (ay)
          </label>
          <Input
            id="fin-term"
            inputMode="numeric"
            value={value.term_months}
            onChange={(event) => onChange({ ...value, term_months: event.target.value })}
          />
        </div>

        <div className="w-56">
          <label htmlFor="fin-product-type" className="mb-1 block text-sm text-text-500">
            Ürün Türü
          </label>
          <Select
            value={value.product_type}
            onValueChange={(next) =>
              onChange({ ...value, product_type: next as FinancingFormState["product_type"] })
            }
          >
            <SelectTrigger id="fin-product-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRODUCT_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {taxonomyLabel(type)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button type="submit" disabled={isPending}>
          {isPending ? "Hesaplanıyor…" : "Hesapla"}
        </Button>
      </div>

      {banks.length > 0 && (
        <fieldset>
          <legend className="mb-2 text-sm text-text-500">
            Bankalar (opsiyonel, boşsa tümü)
          </legend>
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
      )}
    </form>
  );
}
