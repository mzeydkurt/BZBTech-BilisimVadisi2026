import { Copy, PanelLeftOpen, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ChatForm } from "@/components/chat/ChatForm";
import { ChatMatchCard } from "@/components/chat/ChatResultCard";
import { ForbiddenTermsAlert } from "@/components/chat/ForbiddenTermsAlert";
import { AggregatePanel } from "@/components/chat/AggregatePanel";
import { EvidenceDisclosure } from "@/components/chat/EvidenceDisclosure";
import { ModelSelector } from "@/components/chat/ModelSelector";
import { SessionHistory } from "@/components/chat/SessionHistory";
import { GroundingNotice } from "@/components/chat/GroundingNotice";
import { RelaxationHints } from "@/components/chat/RelaxationHints";
import { RetrievalStrip } from "@/components/chat/RetrievalStrip";
import { UnderstoodChips } from "@/components/chat/UnderstoodChips";
import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { useQueryClient } from "@tanstack/react-query";

import { useBanks } from "@/hooks/useBanks";
import {
  readStoredSessionId,
  useChat,
  useChatSession,
  useEndChatSession,
  writeStoredSessionId,
} from "@/hooks/useChat";
import { ApiError } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type {
  ChatResponse,
  ChatSessionMessage,
  ChatTopMatch,
  RelaxationHintOut,
  UnderstoodFilter,
} from "@/types/api";

interface Message {
  role: "user" | "assistant";
  text: string;
  response?: ChatResponse;
  failed?: boolean;
  /** Başarısız turda yeniden deneme için. */
  retryQuery?: string;
  turnIndex?: number;
}

/** Çip kaldırıldıktan sonra kalan sorgu bu uzunluğun altındaysa çalıştırılmaz. */
const MIN_REFINE_LENGTH = 2;

function matchHref(m: ChatTopMatch): string {
  if (m.detail_path) return m.detail_path;
  if (m.entity_type === "campaign") return `/campaigns/${m.id}`;
  if (m.entity_type === "product" || m.entity_type === "product_rate") {
    return `/products/${m.id}`;
  }
  if (m.entity_type === "glossary") return "/chat";
  return "/chat";
}

/** Eski yanıtlardaki [1] / [N] atıflarını temizle. */
function cleanAnswerText(text: string): string {
  return text
    .replace(/\s*\[(?:\d+|N)\]/gi, "")
    .replace(/ {2,}/g, " ")
    .trim();
}

function messagesFromSession(msgs: ChatSessionMessage[]): Message[] {
  const sirali = [...msgs].sort((a, b) => {
    if (a.turn_index !== b.turn_index) return a.turn_index - b.turn_index;
    const ra = a.role === "user" ? 0 : 1;
    const rb = b.role === "user" ? 0 : 1;
    return ra - rb;
  });
  return sirali.map((m) => ({
    role: m.role,
    text: m.content,
    turnIndex: m.turn_index,
    response:
      m.role === "assistant"
        ? (m.response_json ?? m.response ?? undefined)
        : undefined,
  }));
}

/**
 * Yuklenen gecmisin son assistant turundaki `completion_id`.
 *
 * Gecmis yuklendikten sonra sorulan soru bu tura baglanir; aksi halde sunucu
 * "son tur"u varsayar ve kullanici baska bir oturumdan devam ederken baglam
 * kopar.
 */
function zincirUcunuBul(msgs: ChatSessionMessage[]): string | null {
  const sirali = [...msgs].sort((a, b) => a.turn_index - b.turn_index);
  for (let i = sirali.length - 1; i >= 0; i -= 1) {
    const m = sirali[i];
    if (m?.role === "assistant" && m.completion_id) return m.completion_id;
  }
  return null;
}

function TopMatchCards({ data }: { data: ChatResponse }) {
  const matches = (data.top_matches ?? []).slice(0, 3);
  if (matches.length > 0) {
    return <MatchGrid items={matches} />;
  }

  const fallback: ChatTopMatch[] = [
    ...data.results.slice(0, 3).map((r) => ({
      entity_type: "campaign",
      id: r.campaign_id,
      title: r.title,
      bank_name: r.bank_name,
      score: "0",
      source_url: r.source_url,
      reason: r.summary,
      detail_path: `/campaigns/${r.campaign_id}`,
    })),
    ...data.products.slice(0, 3).map((p) => ({
      entity_type: "product",
      id: p.product_id,
      title: p.product_name,
      bank_name: p.bank_name,
      score: "0",
      source_url: p.source_url,
      reason:
        p.profit_rate_pct != null ? `Oran: ${formatPercent(p.profit_rate_pct)}` : null,
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

function MatchGrid({ items }: { items: ChatTopMatch[] }) {
  const cols =
    items.length === 1
      ? "sm:grid-cols-1"
      : items.length === 2
        ? "sm:grid-cols-2"
        : "sm:grid-cols-3";
  return (
    <div className={`mt-3 grid grid-cols-1 gap-2 ${cols}`}>
      {items.map((m) => (
        <ChatMatchCard key={`${m.entity_type}-${m.id}`} match={m} href={matchHref(m)} />
      ))}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 text-[11px] text-text-500 hover:text-text-700"
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      <Copy className="h-3 w-3" aria-hidden="true" />
      {copied ? "Kopyalandı" : "Kopyala"}
    </button>
  );
}

function AssistantBubble({
  msg,
  onRetry,
  onRefine,
}: {
  msg: Message;
  onRetry?: () => void;
  /** Bir süzgeç çipi kaldırıldığında sorguyu o ifade olmadan yeniden çalıştırır. */
  onRefine?: (query: string) => void;
}) {
  if (msg.failed) {
    return (
      <div className="max-w-[90%] space-y-2">
        <div className="rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm text-text-900 shadow-sm ring-1 ring-border">
          <p>{msg.text}</p>
          {onRetry && (
            <button
              type="button"
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-900"
              onClick={onRetry}
            >
              <RotateCcw className="h-3 w-3" aria-hidden="true" />
              Yeniden dene
            </button>
          )}
        </div>
      </div>
    );
  }

  const data = msg.response;
  if (!data) {
    return (
      <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm text-text-700 shadow-sm ring-1 ring-border">
        Yanıt hazırlanıyor…
      </div>
    );
  }

  const answerText = cleanAnswerText(data.answer.text);
  // Oran karşılaştırması dışında yön notu gösterme (kampanya sohbeti).
  const showDirection =
    Boolean(data.direction_note) &&
    (Boolean(data.comparison) || (data.products.length > 0 && data.results.length === 0));

  return (
    <div className="max-w-[90%] space-y-1">
      <div className="rounded-2xl rounded-bl-md bg-surface px-4 py-3 text-sm leading-relaxed text-text-900 shadow-sm ring-1 ring-border">
        {data.forbidden_terms_warning && (
          <div className="mb-2">
            <ForbiddenTermsAlert message={data.forbidden_terms_warning} />
          </div>
        )}
        <p className="whitespace-pre-wrap">{answerText}</p>
        {data.clarification_needed && data.clarification_question && (
          <p className="mt-2 text-amber-800">{data.clarification_question}</p>
        )}
        {showDirection && data.direction_note && (
          <p className="mt-2 text-xs text-brand-800">{data.direction_note}</p>
        )}
        <div className="mt-2">
          <CopyButton text={answerText} />
        </div>
      </div>
      <TopMatchCards data={data} />

      {/*
        ⚠️ Backend bu üç bloğu ZATEN üretiyordu; arayüz onları kullanmadığı için
        atıyordu. Sistemin soruyu nasıl anladığı, hangi süzgecin ne elediği ve
        hangi sayının doğrulanamadığı gizlenemez — kaynağı gösterilemeyen bir
        finansal iddia gösterilemez.
      */}
      <UnderstoodChips
        filters={data.understood}
        onRemove={(filtre) => {
          if (!onRefine) return;
          const temiz = data.query
            .replace(new RegExp(filtre.evidence, "gi"), " ")
            .replace(/\s+/g, " ")
            .trim();
          if (temiz.length >= MIN_REFINE_LENGTH) onRefine(temiz);
        }}
      />

      <GroundingNotice answer={data.answer} />

      {/*
        Kanıt metni KATLANABİLİR ama VAR. `TopMatchCards` yalnızca başlık ve
        bağlantı gösteriyor; yanıtın hangi cümleye dayandığı bankanın sayfasına
        gidilmeden görülemiyordu.
      */}
      <AggregatePanel data={data.aggregate} />

      <EvidenceDisclosure results={data.results} products={data.products} />

      {data.results.length === 0 && data.relaxation_hints.length > 0 && (
        <RelaxationHints
          hints={data.relaxation_hints}
          understood={data.understood}
          onRelax={(oneri: RelaxationHintOut) => {
            if (!onRefine) return;
            const cip: UnderstoodFilter | undefined = data.understood.find(
              (filtre) => filtre.kind === oneri.kind,
            );
            if (!cip) return;
            const temiz = data.query
              .replace(new RegExp(cip.evidence, "gi"), " ")
              .replace(/\s+/g, " ")
              .trim();
            if (temiz.length >= MIN_REFINE_LENGTH) onRefine(temiz);
          }}
        />
      )}

      <RetrievalStrip report={data.retrieval} />
    </div>
  );
}

export function ChatPage() {
  const [query, setQuery] = useState("");
  const [bankCode, setBankCode] = useState<string | undefined>(undefined);
  const [sessionId, setSessionId] = useState<string | null>(() => readStoredSessionId());
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(!sessionId);
  const [pendingClarification, setPendingClarification] = useState<string | null>(null);
  // Model secimi ISTEK BASINA gonderilir; sunucu .env yazmaz.
  // null = sunucunun yapilandirdigi model kullanilir.
  const [modelId, setModelId] = useState<string | null>(null);
  const [gecmisAcik, setGecmisAcik] = useState(true);
  // Sohbet zincirinin ucu: sunucu baglami HANGI cevaptan devralacagini bilsin.
  // Bos birakilirsa sunucu "son tur"u varsayar; gecmisten eski bir tura
  // donuldugunde bu yanlis bagalam tasir.
  const [zincirUcu, setZincirUcu] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: banks } = useBanks();
  const mutation = useChat();
  const endSession = useEndChatSession();
  const sessionQuery = useChatSession(sessionId && !historyLoaded ? sessionId : null);

  useEffect(() => {
    if (!sessionId) {
      setHistoryLoaded(true);
      return;
    }
    if (sessionQuery.isSuccess && sessionQuery.data) {
      if (sessionQuery.data.ended_at) {
        writeStoredSessionId(null);
        setSessionId(null);
        setMessages([]);
        setZincirUcu(null);
      } else {
        const gecmis = sessionQuery.data.messages ?? [];
        setMessages(messagesFromSession(gecmis));
        setZincirUcu(zincirUcunuBul(gecmis));
      }
      setHistoryLoaded(true);
    } else if (sessionQuery.isError) {
      const err = sessionQuery.error;
      if (err instanceof ApiError && (err.code === "HTTP_404" || err.code.includes("404"))) {
        writeStoredSessionId(null);
        setSessionId(null);
      }
      setHistoryLoaded(true);
    }
  }, [sessionId, sessionQuery.isSuccess, sessionQuery.isError, sessionQuery.data, sessionQuery.error]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, mutation.isPending]);

  const persistSession = (id: string | null) => {
    setSessionId(id);
    writeStoredSessionId(id);
  };

  const runQuery = (text: string, opts?: { replaceFailedIndex?: number }) => {
    const trimmed = text.trim();
    if (trimmed.length < 2) return;

    let finalQuery = trimmed;
    if (pendingClarification && opts?.replaceFailedIndex === undefined) {
      finalQuery = `${pendingClarification} ${trimmed}`;
      setPendingClarification(null);
    }

    if (opts?.replaceFailedIndex !== undefined) {
      setMessages((prev) =>
        prev.filter((_, i) => i !== opts.replaceFailedIndex && i !== opts.replaceFailedIndex! - 1),
      );
    }

    setMessages((prev) => [...prev, { role: "user", text: finalQuery }]);
    setQuery("");

    mutation.mutate(
      {
        query: finalQuery,
        bank_code: bankCode ?? null,
        session_id: sessionId,
        model_id: modelId,
        parent_completion_id: zincirUcu,
      },
      {
        onSuccess: (data) => {
          if (data.session_id) persistSession(data.session_id);
          if (data.completion_id) setZincirUcu(data.completion_id);
          setMessages((prev) => [
            ...prev,
            { role: "assistant", text: data.answer.text, response: data },
          ]);
          if (data.clarification_needed && data.clarification_question) {
            setPendingClarification(finalQuery);
          }
          void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
        },
        onError: () => {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              text: "Sorgu yanıtlanamadı. Lütfen tekrar deneyin.",
              failed: true,
              retryQuery: finalQuery,
            },
          ]);
        },
      },
    );
  };

  const handleOpenSession = (key: string) => {
    if (key === sessionId) return;
    setMessages([]);
    setPendingClarification(null);
    setZincirUcu(null);
    setHistoryLoaded(false);
    persistSession(key);
  };

  const handleNewSession = () => {
    persistSession(null);
    setMessages([]);
    setPendingClarification(null);
    setZincirUcu(null);
    setHistoryLoaded(true);
  };

  const handleEndSession = () => {
    const key = sessionId;
    const clearLocal = () => {
      persistSession(null);
      setMessages([]);
      setPendingClarification(null);
      setZincirUcu(null);
    };
    if (!key) {
      clearLocal();
      return;
    }
    endSession.mutate(key, {
      onSettled: clearLocal,
    });
  };

  const bos = messages.length === 0 && !mutation.isPending && historyLoaded;

  return (
    <div className="flex h-[calc(100vh-2rem)] overflow-hidden rounded-lg border border-border bg-surface">
      {/*
        Sohbet geçmişi VERİTABANINDA tutulur (`chat_sessions` / `chat_messages`);
        localStorage yalnızca "hangi oturum açıktı" bilgisini taşır. Bu yüzden
        tarayıcı temizlenince ya da başka makineden girilince geçmiş kaybolmaz.
      */}
      {gecmisAcik && (
        <SessionHistory
          activeKey={sessionId}
          onOpen={handleOpenSession}
          onNew={handleNewSession}
          onClose={() => setGecmisAcik(false)}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            {!gecmisAcik && (
              <button
                type="button"
                onClick={() => setGecmisAcik(true)}
                aria-label="Sohbet geçmişini aç"
                className="rounded border border-border p-1.5 text-text-500 transition-colors hover:border-brand-500 hover:text-text-900"
              >
                <PanelLeftOpen className="h-4 w-4" aria-hidden="true" />
              </button>
            )}
            <div>
              <h1 className="text-base font-semibold text-text-900">Katibim-AI</h1>
              <p className="text-xs text-text-500">
                Kampanya, finansman ve katılma hesabı sorularınızı doğal dille sorun.
              </p>
            </div>
          </div>

          {/* Model seçimi istek başınadır; sunucu yapılandırması değişmez. */}
          <ModelSelector value={modelId} onChange={setModelId} />
        </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-4">
        {!historyLoaded && (
          <p className="px-2 text-sm text-text-500">Önceki sohbet yükleniyor…</p>
        )}

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
          {messages.map((msg, index) => {
            const key =
              msg.turnIndex !== undefined
                ? `${msg.turnIndex}-${msg.role}`
                : `${msg.role}-${index}`;
            return msg.role === "user" ? (
              <div key={key} className="flex justify-end">
                <div className="max-w-[85%] space-y-1">
                  <div className="rounded-2xl rounded-br-md bg-brand-700 px-4 py-2.5 text-sm leading-relaxed text-white">
                    {msg.text}
                  </div>
                  <div className="flex justify-end">
                    <CopyButton text={msg.text} />
                  </div>
                </div>
              </div>
            ) : (
              <div key={key} className="flex justify-start">
                <AssistantBubble
                  msg={msg}
                  onRefine={(yeni) => runQuery(yeni)}
                  onRetry={
                    msg.failed && msg.retryQuery
                      ? () => runQuery(msg.retryQuery!, { replaceFailedIndex: index })
                      : undefined
                  }
                />
              </div>
            );
          })}
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
        {(messages.length > 0 || sessionId) && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-2 h-7 text-xs text-text-500"
            disabled={endSession.isPending}
            onClick={handleEndSession}
          >
            {endSession.isPending ? "Sonlandırılıyor…" : "Sohbeti sonlandır"}
          </Button>
        )}
        </div>
      </div>
    </div>
  );
}
