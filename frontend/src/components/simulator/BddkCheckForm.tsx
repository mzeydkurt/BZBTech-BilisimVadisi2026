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
  asset_type: "tasit" | "konut";
  asset_value_try: string;
  energy_class: string;
}

interface BddkCheckFormProps {
  value: BddkFormState;
  onChange: (next: BddkFormState) => void;
  onSubmit: () => void;
  isPending: boolean;
}

export function BddkCheckForm({ value, onChange, onSubmit, isPending }: BddkCheckFormProps) {
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
          onValueChange={(next) => onChange({ ...value, asset_type: next as BddkFormState["asset_type"] })}
        >
          <SelectTrigger id="bddk-asset-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="konut">Konut</SelectItem>
            <SelectItem value="tasit">Taşıt</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="w-48">
        <label htmlFor="bddk-value" className="mb-1 block text-sm text-text-500">
          Varlık Değeri (TL)
        </label>
        <Input
          id="bddk-value"
          inputMode="numeric"
          value={value.asset_value_try}
          onChange={(event) => onChange({ ...value, asset_value_try: event.target.value })}
        />
      </div>

      {value.asset_type === "konut" && (
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
      )}

      <Button type="submit" disabled={isPending}>
        {isPending ? "Kontrol ediliyor…" : "Kontrol Et"}
      </Button>
    </form>
  );
}
