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

const PRODUCT_TYPES = ["tasit_finansmani", "konut_finansmani", "ihtiyac_finansmani"] as const;

export interface FinancingFormState {
  amount_try: string;
  term_months: string;
  product_type: (typeof PRODUCT_TYPES)[number];
}

interface FinancingFormProps {
  value: FinancingFormState;
  onChange: (next: FinancingFormState) => void;
  onSubmit: () => void;
  isPending: boolean;
}

export function FinancingForm({ value, onChange, onSubmit, isPending }: FinancingFormProps) {
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
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
    </form>
  );
}
