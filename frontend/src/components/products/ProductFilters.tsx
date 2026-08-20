import { taxonomyLabel } from "@/lib/taxonomy";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Bank, RateType } from "@/types/api";

const PRODUCT_TYPES = [
  "finansman",
  "ihtiyac_finansmani",
  "konut_finansmani",
  "tasit_finansmani",
  "kart",
  "alisveris_puani",
  "yeni_musteri",
  "yatirim_urunu",
  "birikim_katilma_hesabi",
  "sigorta",
  "pos_uye_isyeri",
  "dijital_bankacilik",
  "odeme_fatura",
  "kobi_ticari",
  "isyeri_finansmani",
] as const;

const RATE_TYPE_OPTIONS: { value: RateType; label: string }[] = [
  { value: "financing_rate", label: "Finansman maliyeti" },
  { value: "participation_yield", label: "Katılma getirisi" },
  { value: "profit_sharing_ratio", label: "Katılımcı payı" },
];

export interface ProductFilterState {
  bank_code?: string;
  product_type?: string;
  rate_type?: RateType;
}

interface ProductFiltersProps {
  banks: Bank[];
  value: ProductFilterState;
  onChange: (next: ProductFilterState) => void;
}

const ALL = "__all__";

export function ProductFilters({ banks, value, onChange }: ProductFiltersProps) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-56">
          <label htmlFor="product-bank" className="mb-1 block text-sm text-text-500">
            Banka
          </label>
          <Select
            value={value.bank_code ?? ALL}
            onValueChange={(next) =>
              onChange({ ...value, bank_code: next === ALL ? undefined : next })
            }
          >
            <SelectTrigger id="product-bank">
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

        <div className="w-56">
          <label htmlFor="product-type" className="mb-1 block text-sm text-text-500">
            Ürün Türü
          </label>
          <Select
            value={value.product_type ?? ALL}
            onValueChange={(next) =>
              onChange({ ...value, product_type: next === ALL ? undefined : next })
            }
          >
            <SelectTrigger id="product-type">
              <SelectValue placeholder="Tüm ürün türleri" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm ürün türleri</SelectItem>
              {PRODUCT_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {taxonomyLabel(type)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-56">
          <label htmlFor="product-rate-type" className="mb-1 block text-sm text-text-500">
            Oran Türü
          </label>
          <Select
            value={value.rate_type ?? ALL}
            onValueChange={(next) =>
              onChange({ ...value, rate_type: next === ALL ? undefined : (next as RateType) })
            }
          >
            <SelectTrigger id="product-rate-type">
              <SelectValue placeholder="Tüm oran türleri" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm oran türleri</SelectItem>
              {RATE_TYPE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}
