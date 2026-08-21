import { taxonomyLabel } from "@/lib/taxonomy";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Bank } from "@/types/api";

/** `app/core/vocab.py::FINANSMAN_TIPLERI` ile birebir aynı slug kümesi. */
const FINANSMAN_TIPLERI = [
  "finansman",
  "ihtiyac_finansmani",
  "konut_finansmani",
  "tasit_finansmani",
  "isyeri_finansmani",
  "gayrimenkul_finansmani",
  "alisveris_finansmani",
  "surdurulebilir_finansman",
  "arsa_finansmani",
  "egitim_finansmani",
  "karz_i_hasen",
  "digital_arac_finansmani",
  "marka_ozel_finansman",
] as const;

export interface FinancingFilterState {
  bank_code?: string;
  product_type?: string;
}

interface FinancingFiltersProps {
  banks: Bank[];
  value: FinancingFilterState;
  onChange: (next: FinancingFilterState) => void;
}

const ALL = "__all__";

export function FinancingFilters({ banks, value, onChange }: FinancingFiltersProps) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <label htmlFor="financing-bank" className="mb-1 block text-sm text-text-500">
            Banka
          </label>
          <Select
            value={value.bank_code ?? ALL}
            onValueChange={(next) =>
              onChange({ ...value, bank_code: next === ALL ? undefined : next })
            }
          >
            <SelectTrigger id="financing-bank">
              <SelectValue placeholder="Tüm bankalar" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm bankalar</SelectItem>
              {banks.map((bank) => (
                <SelectItem key={bank.code} value={bank.code}>
                  {bank.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-64">
          <label htmlFor="financing-type" className="mb-1 block text-sm text-text-500">
            Finansman Türü
          </label>
          <Select
            value={value.product_type ?? ALL}
            onValueChange={(next) =>
              onChange({ ...value, product_type: next === ALL ? undefined : next })
            }
          >
            <SelectTrigger id="financing-type">
              <SelectValue placeholder="Tüm finansman türleri" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm finansman türleri</SelectItem>
              {FINANSMAN_TIPLERI.map((type) => (
                <SelectItem key={type} value={type}>
                  {taxonomyLabel(type)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}
