import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useBddkBands } from "@/hooks/useSimulator";
import type { BddkBandOut } from "@/types/api";

const ENERJI_SINIFLARI = [
  { value: "A", label: "A veya B" },
  { value: "C", label: "C" },
  { value: "DIGER", label: "D ve altı" },
];

/**
 * Bandın temsil ettiği değer: üst sınır, yoksa alt sınır.
 *
 * ⚠️ BDDK tavanı `değer × oran` ile hesaplanır; bant tek başına kesin tutarı
 * vermez. Üst sınır seçilir — kullanıcı "bu bandın en üstündeysem ne olur"
 * sorusunun yanıtını arar ve bandın en kötü hâli budur.
 */
function bandDegeri(band: BddkBandOut): string {
  return band.value_max ?? band.value_min ?? band.amount_max ?? band.amount_min ?? "";
}

export interface BddkFormState {
  asset_type: "tasit" | "konut" | "ihtiyac";
  asset_value_try: string;
  energy_class: string;
  first_home: boolean;
}

interface BddkCheckFormProps {
  value: BddkFormState;
  onChange: (next: BddkFormState) => void;
  onSubmit: () => void;
  isPending: boolean;
}

export function BddkCheckForm({ value, onChange, onSubmit, isPending }: BddkCheckFormProps) {
  const { data: bantlar } = useBddkBands();
  const aileBantlari = bantlar?.[value.asset_type]?.bands ?? [];
  const valueLabel =
    value.asset_type === "ihtiyac"
      ? "Finansman Tutarı"
      : value.asset_type === "konut"
        ? "Ekspertiz Değeri"
        : "Kasko / Fatura Değeri";

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="w-40">
        <label htmlFor="bddk-asset-type" className="mb-1 block text-sm text-text-500">
          Varlık Türü
        </label>
        <Select
          value={value.asset_type}
          onValueChange={(next) =>
            onChange({
              ...value,
              asset_type: next as BddkFormState["asset_type"],
              // Bantlar varlık türüne özgüdür; taşıt bandı konutta anlamsızdır.
              asset_value_try: "",
            })
          }
        >
          <SelectTrigger id="bddk-asset-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="konut">Konut</SelectItem>
            <SelectItem value="tasit">Taşıt</SelectItem>
            <SelectItem value="ihtiyac">İhtiyaç</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="w-48">
        <label htmlFor="bddk-value" className="mb-1 block text-sm text-text-500">
          {valueLabel}
        </label>
        <Select
          value={value.asset_value_try || undefined}
          onValueChange={(next) => onChange({ ...value, asset_value_try: next })}
        >
          <SelectTrigger id="bddk-value">
            <SelectValue placeholder="Değer aralığı seçin" />
          </SelectTrigger>
          <SelectContent>
            {aileBantlari.map((band) => (
              <SelectItem key={band.label} value={bandDegeri(band)}>
                {band.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {value.asset_type === "konut" && (
        <>
          <div className="w-40">
            <label htmlFor="bddk-energy" className="mb-1 block text-sm text-text-500">
              Enerji Sınıfı
            </label>
            <Select
              value={value.energy_class || "DIGER"}
              onValueChange={(next) => onChange({ ...value, energy_class: next })}
            >
              <SelectTrigger id="bddk-energy">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ENERJI_SINIFLARI.map((sinif) => (
                  <SelectItem key={sinif.value} value={sinif.value}>
                    {sinif.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="w-44">
            <label htmlFor="bddk-first-home" className="mb-1 block text-sm text-text-500">
              Konut Durumu
            </label>
            <Select
              value={value.first_home ? "first" : "second"}
              onValueChange={(next) => onChange({ ...value, first_home: next === "first" })}
            >
              <SelectTrigger id="bddk-first-home">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="first">İlk konut</SelectItem>
                <SelectItem value="second">İkinci / sonraki</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      <Button type="submit" disabled={isPending || !value.asset_value_try}>
        {isPending ? "Kontrol ediliyor…" : "Kontrol Et"}
      </Button>
    </form>
  );
}
