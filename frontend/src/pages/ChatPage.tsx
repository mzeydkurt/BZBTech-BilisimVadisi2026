import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ChatForm } from "@/components/chat/ChatForm";
import { ForbiddenTermsAlert } from "@/components/chat/ForbiddenTermsAlert";
import { ErrorState } from "@/components/common/ErrorState";
import { useBanks } from "@/hooks/useBanks";
import { useChat } from "@/hooks/useChat";
import { formatPercent } from "@/lib/format";
import type { ChatResponse, ChatTopMatch } from "@/types/api";

interface Message {
  role: "user" | "assistant";
  text: string;
  response?: ChatResponse;
}

function matchHref(m: ChatTopMatch): string {
  if (m.detail_path) return m.detail_path;
  if (m.entity_type === "campaign") return `/campaigns?id=${m.id}`;
  if (m.entity_type === "product" || m.entity_type === "product_rate") {
    return `/products/${m.id}`;
  }
  if (m.entity_type === "glossary") return "/chat";
  return "/chat";
}

function SourceLine({ data }: { data: ChatResponse }) {
  const kaynaklar: { label: string; href: string | null }[] = [];
  const top = data.top_matches ?? [];

  for (const m of top.slice(0, 3)) {
    kaynaklar.push({
      label: m.bank_name ? `${m.bank_name} — ${m.title}` : m.title,
      href: matchHref(m),
    });
  }
  if (kaynaklar.length === 0) {
    for (const r of data.results.slice(0, 3)) {
      kaynaklar.push({
        label: `${r.bank_name} — ${r.title}`,
        href: `/campaigns?id=${r.campaign_id}`,
      });
    }
  }
  if (kaynaklar.length === 0) {
    for (const p of data.products.slice(0, 3)) {
      kaynaklar.push({
        label: `${p.bank_name} — ${p.product_name}`,
        href: `/products/${p.product_id}`,
      });
    }
  }
  if (kaynaklar.length === 0) return null;

  return (
    <p className="mt-2 text-xs text-text-500">
      <span className="font-medium text-text-700">Kaynaklar: </span>
      {kaynaklar.map((k, i) => (
        <span key={`${k.label}-${i}`}>
          {i > 0 && " · "}
          {k.href ? (
            <Link to={k.href} className="text-brand-700 hover:underline">
              {k.label}
            </Link>
          ) : (
            k.label
          )}
        </span>
      ))}
    </p>
  );
}

function TopMatchCards({ data }: { data: ChatResponse }) {
  const matches = (data.top_matches ?? []).slice(0, 3);
  if (matches.length === 0) {
    // Geriye uyumluluk: top_matches yoksa results/products'tan kart üret.
    const fallback: ChatTopMatch[] = [
      ...data.results.slice(0, 3).map((r) => ({
        entity_type: "campaign",
        id: r.campaign_id,
        title: r.title,
        bank_name: r.bank_name,
        score: "0",
        source_url: r.source_url,
        reason: r.summary,
        detail_path: `/campaigns?id=${r.campaign_id}`,
      })),
      ...data.products.slice(0, 3).map((p) => ({
        entity_type: "product",
        id: p.product_id,
        title: p.product_name,
        bank_name: p.bank_name,
        score: "0",
        source_url: p.source_url,
        reason:
          p.profit_rate_pct != null
            ? `Oran: ${formatPercent(p.profit_rate_pct)}`
            : null,
        detail_path:
          p.rate_type === "participation_yield" ||
          p.rate_type === "profit_sharing_ratio"
            ? "/katilim-hesabi"
            : `/products/${p.product_id}`,
      })),
    ].slice(0, 3);
    if (fallback.length === 0) return null;
    return <MatchGrid items={fallback} />;
  }
  return <MatchGrid items={matches} />;
}

function MatchGrid({ items }: { items: ChatTopMatch[] }) {
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-3">
      {items.map((m) => (
        <Link
          key={`${m.entity_type}-${m.id}`}
          to={matchHref(m)}
          className="block rounded-lg border border-border bg-surface px-3 py-2 transition-colors hover:border-brand-500"
        >
          {m.bank_name && <p className="text-[11px] text-text-500">{m.bank_name}</p>}
          <p className="text-sm font-medium text-text-900 line-clamp-2">{m.title}</p>
          {m.reason && (
            <p className="mt-1 text-xs text-text-500 line-clamp-2">{m.reason}</p>
          )}
        </Link>
      ))}
    </div>
  );
}

function AssistantBubble({ msg }: { msg: Message }) {
  const data = msg.response;
  if (!data) {
    return (
      <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm text-text-700 shadow-sm ring-1 ring-border">
        Yanıt hazırlanıyor…
      </div>
    );
  }

  return (
    <div className="max-w-[90%] space-y-1">
      <div className="rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm text-text-900 shadow-sm ring-1 ring-border">
        {data.forbidden_terms_warning && (
          <div className="mb-2">
            <ForbiddenTermsAlert message={data.forbidden_terms_warning} />
          </div>
        )}
        <p className="whitespace-pre-wrap">{data.answer.text}</p>
        {data.clarification_needed && data.clarification_question && (
          <p className="mt-2 text-amber-800">{data.clarification_question}</p>
        )}
        {data.direction_note && (
          <p className="mt-2 text-xs text-brand-800">{data.direction_note}</p>
        )}
        <SourceLine data={data} />
      </div>
      <TopMatchCards data={data} />
    </div>
  );
}

export function ChatPage() {
  const [query, setQuery] = useState("");
  const [bankCode, setBankCode] = useState<string | undefined>(undefined);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingClarification, setPendingClarification] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: banks } = useBanks();
  const mutation = useChat();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, mutation.isPending]);

  const runQuery = (text: string) => {
    const trimmed = text.trim();
    if (trimmed.length < 2) return;

    let finalQuery = trimmed;
    if (pendingClarification) {
      finalQuery = `${pendingClarification} ${trimmed}`;
      setPendingClarification(null);
    }

    setMessages((prev) => [...prev, { role: "user", text: finalQuery }]);
    setQuery("");

    mutation.mutate(
      { query: finalQuery, bank_code: bankCode ?? null },
      {
        onSuccess: (data) => {
          setMessages((prev) => [
            ...prev,
            { role: "assistant", text: data.answer.text, response: data },
          ]);
          if (data.clarification_needed && data.clarification_question) {
            setPendingClarification(finalQuery);
          }
        },
        onError: () => {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              text: "Sorgu yanıtlanamadı. Lütfen tekrar deneyin.",
            },
          ]);
        },
      },
    );
  };

  const bos = messages.length === 0 && !mutation.isPending;

  return (
    <div className="flex h-[calc(100vh-2rem)] flex-col">
      <div className="shrink-0 border-b border-border pb-3">
        <h1 className="text-xl font-semibold text-text-900">Katibim AI Asistan</h1>
        <p className="mt-1 text-sm text-text-500">
          Kampanya, finansman ve katılma hesabı sorularınızı doğal dille sorun.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-4">
        {bos && (
          <div className="mx-auto max-w-xl space-y-4 px-2 py-8 text-center">
            <p className="text-sm text-text-500">
              Örnek bir soru seçin veya aşağıya yazın.
            </p>
            <ChatForm
              query={query}
              onQueryChange={setQuery}
              bankCode={bankCode}
              onBankCodeChange={setBankCode}
              banks={banks ?? []}
              isPending={mutation.isPending}
              onSubmit={() => runQuery(query)}
              onExampleClick={(ornek) => runQuery(ornek)}
              compact={false}
              showExamples
              hideComposer
            />
          </div>
        )}

        <div className="mx-auto flex max-w-2xl flex-col gap-4 px-2">
          {messages.map((msg, index) =>
            msg.role === "user" ? (
              <div key={`u-${index}`} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-700 px-4 py-2.5 text-sm text-white">
                  {msg.text}
                </div>
              </div>
            ) : (
              <div key={`a-${index}`} className="flex justify-start">
                <AssistantBubble msg={msg} />
              </div>
            ),
          )}
          {mutation.isPending && (
            <div className="flex justify-start">
              <div className="rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm text-text-500 ring-1 ring-border">
                Düşünüyor…
              </div>
            </div>
          )}
          {mutation.isError && !mutation.isPending && (
            <ErrorState error={mutation.error} title="Sorgu yanıtlanamadı" />
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-border pt-3">
        {pendingClarification && (
          <p className="mb-2 text-xs text-amber-800">
            Netleştirme bekleniyor — yanıtınız önceki soruyla birleştirilecek.
          </p>
        )}
        <ChatForm
          query={query}
          onQueryChange={setQuery}
          bankCode={bankCode}
          onBankCodeChange={setBankCode}
          banks={banks ?? []}
          isPending={mutation.isPending}
          onSubmit={() => runQuery(query)}
          compact
          showExamples={false}
        />
        {messages.length > 0 && (
          <button
            type="button"
            className="mt-2 text-xs text-text-500 hover:text-text-700"
            onClick={() => setMessages([])}
          >
            Sohbeti temizle
          </button>
        )}
      </div>
    </div>
  );
}
