import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ExtractMode } from "@/types/api";

const MODES: { value: ExtractMode; label: string }[] = [
  { value: "hybrid", label: "Hibrit (kural + model)" },
  { value: "rule_only", label: "Yalnızca kural" },
  { value: "llm_only", label: "Yalnızca model" },
];

const MAX_LENGTH = 20_000;

interface ExtractFormProps {
  text: string;
  onTextChange: (value: string) => void;
  mode: ExtractMode;
  onModeChange: (value: ExtractMode) => void;
  onSubmit: () => void;
  isPending: boolean;
}

export function ExtractForm({
  text,
  onTextChange,
  mode,
  onModeChange,
  onSubmit,
  isPending,
}: ExtractFormProps) {
  return (
    <form
      className="space-y-3 rounded-lg border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div>
        <label htmlFor="extract-text" className="mb-1 block text-sm text-text-500">
          Kampanya Metni
        </label>
        <textarea
          id="extract-text"
          value={text}
          onChange={(event) => onTextChange(event.target.value.slice(0, MAX_LENGTH))}
          rows={8}
          className="w-full rounded border border-border bg-surface px-3 py-2 text-base text-text-900 placeholder:text-text-500 transition-colors duration-150 hover:border-text-500"
          placeholder="Bir banka kampanya sayfasından metin yapıştırın…"
        />
        <p className="tabular mt-1 text-right text-xs text-text-500">
          {text.length} / {MAX_LENGTH}
        </p>
      </div>

      <div className="flex items-end gap-3">
        <div className="w-56">
          <label htmlFor="extract-mode" className="mb-1 block text-sm text-text-500">
            Kip
          </label>
          <Select value={mode} onValueChange={(next) => onModeChange(next as ExtractMode)}>
            <SelectTrigger id="extract-mode">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MODES.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button type="submit" disabled={isPending || text.trim().length === 0}>
          {isPending ? "Çıkarılıyor…" : "Çıkar"}
        </Button>
      </div>
    </form>
  );
}
