import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { taxonomyLabel } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { Bank, CampaignCompareRequest, CampaignRankingCriterion } from "@/types/api";

const CAMPAIGN_CRITERIA: { value: CampaignRankingCriterion; label: string }[] = [
  { value: "en_yuksek_odul", label: "En yüksek ödül" },
  { value: "en_dusuk_kar_payi", label: "En düşük kâr payı" },
  { value: "en_uzun_vade", label: "En uzun vade" },
  { value: "en_yuksek_taksit", label: "En yüksek taksit" },
  { value: "en_yuksek_iade_orani", label: "En yüksek iade oranı" },
  { value: "en_yuksek_indirim", label: "En yüksek indirim" },
];

const TUMU = "__tumu__";

/**
 * Kampanyalarda FİİLEN etiketlenmiş ürün türleri, kampanya sayısına göre sıralı.
 *
 * Serbest metin yerine liste: kullanıcının yazdığı `taşıt finansmanı` gibi bir
 * değer sessizce sıfır sonuç döndürüyordu — API hata vermiyor, boş liste dönüyor.
 * Etiketlenmemiş bir tür sunmak da aynı boş sonucu üretirdi; bu yüzden liste
 * `campaign_categories` içindeki gerçek dağılımdan alındı.
 */
const KAMPANYA_URUN_TIPLERI = [
  "kart",
  "alisveris_puani",
  "finansman",
  "yeni_musteri",
  "dijital_bankacilik",
  "alisveris_finansmani",
  "kobi_ticari",
  "ihtiyac_finansmani",
  "birikim_katilma_hesabi",
  "odeme_fatura",
  "tasit_finansmani",
  "sigorta",
  "yatirim_urunu",
  "pos_uye_isyeri",
  "konut_finansmani",
];

export interface CampaignCompareFormState {
  criterion: CampaignRankingCriterion;
  product_type: string;
  bank_codes: string[];
  only_active: boolean;
}

interface CampaignCompareFormProps {
  value: CampaignCompareFormState;
  onChange: (next: CampaignCompareFormState) => void;
  onSubmit: () => void;
  banks: Bank[];
  isPending: boolean;
}

export function toCampaignCompareRequest(
  form: CampaignCompareFormState,
): CampaignCompareRequest {
  return {
    criterion: form.criterion,
    product_type: form.product_type || undefined,
    bank_codes: form.bank_codes.length > 0 ? form.bank_codes : undefined,
    only_active: form.only_active,
    limit: 20,
  };
}

export function CampaignCompareForm({
  value,
  onChange,
  onSubmit,
  banks,
  isPending,
}: CampaignCompareFormProps) {
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
        <div className="w-64">
          <label htmlFor="camp-criterion" className="mb-1 block text-sm text-text-500">
            Ölçüt
          </label>
          <Select
            value={value.criterion}
            onValueChange={(next) =>
              onChange({ ...value, criterion: next as CampaignRankingCriterion })
            }
          >
            <SelectTrigger id="camp-criterion">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CAMPAIGN_CRITERIA.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="w-56">
          <label htmlFor="camp-product-type" className="mb-1 block text-sm text-text-500">
            Ürün / kampanya türü
          </label>
          <Select
            value={value.product_type || TUMU}
            onValueChange={(next) =>
              onChange({ ...value, product_type: next === TUMU ? "" : next })
            }
          >
            <SelectTrigger id="camp-product-type">
              <SelectValue placeholder="Tüm türler" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={TUMU}>Tüm türler</SelectItem>
              {KAMPANYA_URUN_TIPLERI.map((type) => (
                <SelectItem key={type} value={type}>
                  {taxonomyLabel(type)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="flex items-end gap-2 pb-2 text-sm text-text-700">
          <input
            type="checkbox"
            checked={value.only_active}
            onChange={(event) => onChange({ ...value, only_active: event.target.checked })}
            className="accent-brand-700"
          />
          Yalnızca aktif
        </label>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm text-text-500">Bankalar (opsiyonel)</legend>
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

      <Button type="submit" disabled={isPending}>
        {isPending ? "Karşılaştırılıyor…" : "Kampanyaları karşılaştır"}
      </Button>
    </form>
  );
}
