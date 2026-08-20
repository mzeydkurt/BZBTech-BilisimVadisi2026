import { useState } from "react";

import { ChatForm } from "@/components/chat/ChatForm";
import { ChatResultCard } from "@/components/chat/ChatResultCard";
import { ForbiddenTermsAlert } from "@/components/chat/ForbiddenTermsAlert";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { useBanks } from "@/hooks/useBanks";
import { useChat } from "@/hooks/useChat";

export function ChatPage() {
  const [query, setQuery] = useState("");
  const [bankCode, setBankCode] = useState<string | undefined>(undefined);

  const { data: banks } = useBanks();
  const mutation = useChat();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Akıllı Arama</h1>
        <p className="mt-1 text-sm text-text-500">
          Kampanya verisi üzerinde doğal dille soru sorun.
        </p>
      </div>

      <ChatForm
        query={query}
        onQueryChange={setQuery}
        bankCode={bankCode}
        onBankCodeChange={setBankCode}
        banks={banks ?? []}
        isPending={mutation.isPending}
        onSubmit={() => mutation.mutate({ query, bank_code: bankCode ?? null })}
      />

      {mutation.isPending && <LoadingState variant="cards" />}

      {mutation.isError && <ErrorState error={mutation.error} title="Sorgu yanıtlanamadı" />}

      {mutation.isSuccess && (
        <div className="space-y-4">
          {mutation.data.forbidden_terms_warning && (
            <ForbiddenTermsAlert message={mutation.data.forbidden_terms_warning} />
          )}

          <div className="rounded-lg border border-border bg-surface p-4">
            <p className="whitespace-pre-wrap text-sm text-text-900">
              {mutation.data.answer_text}
            </p>
          </div>

          {mutation.data.results.length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {mutation.data.results.map((item) => (
                <ChatResultCard key={item.campaign_id} item={item} />
              ))}
            </div>
          ) : (
            // ⚠️ Boş `results` + dolu `answer_text` BAŞARILI bir yanıttır, hata değil.
            <EmptyState
              title="Bu sorguya uygun kanıt bulunamadı"
              description="Yukarıdaki genel yanıt yine de geçerlidir; farklı bir arama denenebilir."
            />
          )}
        </div>
      )}
    </div>
  );
}
