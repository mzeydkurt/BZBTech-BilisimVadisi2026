import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const CURRENCIES = ["TRY", "USD", "EUR", "XAU", "XAG"] as const;

export interface YieldFormState {
  deposit_try: string;
  term_days: string;
  currency: (typeof CURRENCIES)[number];
}

interface YieldFormProps {
  value: YieldFormState;
  onChange: (next: YieldFormState) => void;
  onSubmit: () => void;
  isPending: boolean;
}

export function YieldForm({ value, onChange, onSubmit, isPending }: YieldFormProps) {
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="w-48">
        <label htmlFor="yield-deposit" className="mb-1 block text-sm text-text-500">
          Katılım Fonu Tutarı
        </label>
        <Input
          id="yield-deposit"
          inputMode="numeric"
          value={value.deposit_try}
          onChange={(event) => onChange({ ...value, deposit_try: event.target.value })}
        />
      </div>

      <div className="w-32">
        <label htmlFor="yield-term" className="mb-1 block text-sm text-text-500">
          Vade (gün)
        </label>
        <Input
          id="yield-term"
          inputMode="numeric"
          value={value.term_days}
          onChange={(event) => onChange({ ...value, term_days: event.target.value })}
        />
      </div>

      <div className="w-32">
        <label htmlFor="yield-currency" className="mb-1 block text-sm text-text-500">
          Para Birimi
        </label>
        <Select
          value={value.currency}
          onValueChange={(next) => onChange({ ...value, currency: next as YieldFormState["currency"] })}
        >
          <SelectTrigger id="yield-currency">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CURRENCIES.map((currency) => (
              <SelectItem key={currency} value={currency}>
                {currency}
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
