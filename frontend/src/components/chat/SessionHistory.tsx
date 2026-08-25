import { useQuery } from "@tanstack/react-query";
import { History, MessageSquareText, Plus, X } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ChatSessionSummary } from "@/types/api";

interface SessionHistoryProps {
  activeKey: string | null;
  onOpen: (sessionKey: string) => void;
  onNew: () => void;
  /** Küçük ekranda panel kapatılabilir olmalı. */
  onClose?: () => void;
}

/**
 * Sohbet geçmişi paneli.
 *
 * ⚠️ GEÇMİŞ VERİTABANINDA, TARAYICIDA DEĞİL. `localStorage` yalnızca "hangi
 * oturum açıktı" bilgisini tutuyor; sohbetin kendisi `chat_sessions` /
 * `chat_messages` tablolarında. Bu yüzden tarayıcı temizlenince ya da başka
 * bir makineden girilince geçmiş KAYBOLMAZ.
 *
 * ⚠️ ÜÇ DURUM AYRI (CLAUDE.md): istek sürerken yükleniyor, istek başarısızsa
 * `ErrorState`, istek başarılı ama kayıt yoksa `EmptyState`. Sonuncusunu
 * ilkinin yerine göstermek, API çöktüğünde "hiç sohbet yok" demek olurdu.
 *
 * ⚠️ BOŞ OTURUMLAR GİZLİ. Sayfa her açıldığında bir oturum anahtarı
 * oluşuyor; kullanıcı soru sormadan çıkarsa geçmiş boş kayıtlarla dolar.
 * Backend bunları varsayılan olarak süzüyor (`include_empty=false`) —
 * silmiyor, gizliyor.
 */
export function SessionHistory({ activeKey, onOpen, onNew, onClose }: SessionHistoryProps) {
  const sorgu = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => api.chatSessions(),
    staleTime: 15_000,
  });

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-neutral-50">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2.5">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-text-700">
          <History className="h-3.5 w-3.5" aria-hidden="true" />
          Sohbet geçmişi
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Geçmiş panelini kapat"
            className="rounded p-0.5 text-text-500 transition-colors hover:bg-border hover:text-text-900 lg:hidden"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
      </div>

      <div className="border-b border-border p-2">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center justify-center gap-1.5 rounded border border-border bg-surface px-3 py-2 text-sm font-medium text-text-900 transition-colors hover:border-brand-500"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          Yeni sohbet
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {sorgu.isPending && <p className="px-1 text-xs text-text-500">Yükleniyor…</p>}

        {sorgu.isError && (
          <ErrorState error={sorgu.error} title="Geçmiş yüklenemedi" />
        )}

        {sorgu.isSuccess && sorgu.data.items.length === 0 && (
          <EmptyState
            title="Henüz sohbet yok"
            description="İlk sorunuzu sorduğunuzda burada listelenir."
          />
        )}

        {sorgu.isSuccess && sorgu.data.items.length > 0 && (
          <ul className="space-y-1">
            {sorgu.data.items.map((oturum: ChatSessionSummary) => {
              const aktif = oturum.session_key === activeKey;
              return (
                <li key={oturum.session_key}>
                  <button
                    type="button"
                    onClick={() => onOpen(oturum.session_key)}
                    className={cn(
                      "w-full rounded px-2 py-2 text-left transition-colors",
                      aktif
                        ? "bg-teal-100 text-text-900"
                        : "text-text-700 hover:bg-surface",
                    )}
                  >
                    <span className="flex items-start gap-1.5">
                      <MessageSquareText
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-500"
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium">
                          {oturum.title ?? "Adsız sohbet"}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-text-500">
                          {formatDateTime(oturum.last_activity_at)}
                          {oturum.turn_count > 0 && ` · ${oturum.turn_count} tur`}
                          {oturum.ended_at && " · kapatıldı"}
                        </span>
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {sorgu.isSuccess && sorgu.data.total > sorgu.data.items.length && (
        // ⚠️ Kırpma sessiz kalmaz: kaç kaydın gösterilmediği yazılır.
        <p className="border-t border-border px-3 py-2 text-[11px] text-text-500">
          {sorgu.data.total} oturumdan son {sorgu.data.items.length} tanesi gösteriliyor.
        </p>
      )}
    </aside>
  );
}
