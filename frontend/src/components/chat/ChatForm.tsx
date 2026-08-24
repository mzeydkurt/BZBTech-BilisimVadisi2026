import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Bank } from "@/types/api";

const ALL = "__all__";

/** Boş sohbette gösterilen örnek sorular. */
export const EXAMPLE_QUERIES = [
  "Ziraat Katılım'ın konut finansmanı oranı ne?",
  "Kuveyt Türk mü daha avantajlı, Albaraka mı?",
  "En yüksek nakit iade veren kampanyalar",
  "Yeni müşterilere özel kampanyalar",
  "Kâr payı oranı ne demek?",
  "Katılma hesabı getirisi hangi bankada yüksek?",
  "Murabaha nedir?",
] as const;

interface ChatFormProps {
  query: string;
  onQueryChange: (value: string) => void;
  bankCode: string | undefined;
  onBankCodeChange: (value: string | undefined) => void;
  banks: Bank[];
  onSubmit: () => void;
  isPending: boolean;
  onExampleClick?: (query: string) => void;
  /** Alt composer düzeni (tek satır). */
  compact?: boolean;
  showExamples?: boolean;
  /** Yalnızca örnek çipleri göster (boş sohbet). */
  hideComposer?: boolean;
}

export function ChatForm({
  query,
  onQueryChange,
  bankCode,
  onBankCodeChange,
  banks,
  onSubmit,
  isPending,
  onExampleClick,
  compact = false,
  showExamples = true,
  hideComposer = false,
}: ChatFormProps) {
  return (
    <div className="space-y-3">
      {showExamples && onExampleClick && (
        <div className="flex flex-wrap justify-center gap-2">
          {EXAMPLE_QUERIES.map((ornek) => (
            <button
              key={ornek}
              type="button"
              className="rounded-md border border-border bg-surface px-2.5 py-1 text-left text-xs text-text-700 hover:border-brand-500 hover:text-brand-700"
              onClick={() => onExampleClick(ornek)}
            >
              {ornek}
            </button>
          ))}
        </div>
      )}

      {!hideComposer && (
        <form
          className={
            compact
              ? "flex items-center gap-2"
              : "flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4"
          }
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div className={compact ? "min-w-0 flex-1" : "min-w-[280px] flex-1"}>
            {!compact && (
              <label htmlFor="chat-query" className="mb-1 block text-sm text-text-500">
                Sorunuz
              </label>
            )}
            <Input
              id="chat-query"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Mesajınızı yazın…"
              autoComplete="off"
            />
          </div>

          <div className={compact ? "w-40 shrink-0" : "w-52"}>
            {!compact && (
              <label htmlFor="chat-bank" className="mb-1 block text-sm text-text-500">
                Banka (opsiyonel)
              </label>
            )}
            <Select
              value={bankCode ?? ALL}
              onValueChange={(next) => onBankCodeChange(next === ALL ? undefined : next)}
            >
              <SelectTrigger id="chat-bank">
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

          <Button type="submit" disabled={isPending || query.trim().length < 2}>
            {isPending ? "…" : "Gönder"}
          </Button>
        </form>
      )}
    </div>
  );
}
