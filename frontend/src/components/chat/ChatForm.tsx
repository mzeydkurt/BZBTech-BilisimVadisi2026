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

interface ChatFormProps {
  query: string;
  onQueryChange: (value: string) => void;
  bankCode: string | undefined;
  onBankCodeChange: (value: string | undefined) => void;
  banks: Bank[];
  onSubmit: () => void;
  isPending: boolean;
}

export function ChatForm({
  query,
  onQueryChange,
  bankCode,
  onBankCodeChange,
  banks,
  onSubmit,
  isPending,
}: ChatFormProps) {
  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="min-w-[280px] flex-1">
        <label htmlFor="chat-query" className="mb-1 block text-sm text-text-500">
          Sorunuz
        </label>
        <Input
          id="chat-query"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="ör. kâr payı oranı en düşük hangi banka"
        />
      </div>

      <div className="w-52">
        <label htmlFor="chat-bank" className="mb-1 block text-sm text-text-500">
          Banka (opsiyonel)
        </label>
        <Select value={bankCode ?? ALL} onValueChange={(next) => onBankCodeChange(next === ALL ? undefined : next)}>
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
        {isPending ? "Aranıyor…" : "Sor"}
      </Button>
    </form>
  );
}
