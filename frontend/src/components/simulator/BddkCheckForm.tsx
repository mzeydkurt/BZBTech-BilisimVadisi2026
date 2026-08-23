import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
  const valueLabel =
    value.asset_type === "ihtiyac"
      ? "Finansman Tutarı (TL)"
      : value.asset_type === "konut"
        ? "Ekspertiz Değeri (TL)"
        : "Kasko / Fatura Değeri (TL)";

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
            onChange({ ...value, asset_type: next as BddkFormState["asset_type"] })
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
        <Input
          id="bddk-value"
          inputMode="numeric"
          value={value.asset_value_try}
          onChange={(event) => onChange({ ...value, asset_value_try: event.target.value })}
        />
      </div>

      {value.asset_type === "konut" && (
        <>
          <div className="w-40">
            <label htmlFor="bddk-energy" className="mb-1 block text-sm text-text-500">
              Enerji Sınıfı
            </label>
            <Input
              id="bddk-energy"
              value={value.energy_class}
              onChange={(event) => onChange({ ...value, energy_class: event.target.value })}
              placeholder="A, B, C…"
            />
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

      <Button type="submit" disabled={isPending}>
        {isPending ? "Kontrol ediliyor…" : "Kontrol Et"}
      </Button>
    </form>
  );
}
