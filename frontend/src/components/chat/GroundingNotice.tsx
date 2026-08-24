import { AlertTriangle, CircleSlash, Cpu, FunctionSquare, ShieldCheck } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { AnswerBlock } from "@/types/api";

/**
 * Yanıtın kaynağı ve denetim sonucu — tek satırlık şerit.
 *
 * ⚠️ DOĞRULANAMAYAN SAYI GİZLENMEZ. Modelin ürettiği bir rakam atıf verilen
 * kartta bulunamadıysa yanıt SİLİNMEZ ama işaretlenir: sessizce göstermek
 * halüsinasyonu en görünür yere koymak, silmek ise kullanıcının neyi
 * kaçırdığını bilmemesi olurdu.
 *
 * ⚠️ `AnswerPanel`'in tamamı değil YALNIZCA denetim kısmı. Yanıt metnini
 * sohbet balonu zaten çiziyor; ikinci kez çizmek aynı cümleyi iki yerde
 * gösterirdi.
 */
const SOURCE_NOTES: Record<string, { label: string; note: string; icon: typeof Cpu }> = {
  model: {
    label: "Yerel model",
    note: "Cümle yerel modelde üretildi; sayılar kaynak kartlara karşı denetlendi.",
    icon: Cpu,
  },
  computed: {
    label: "Hesaplanmış",
    note: "Bu yanıt doğrudan veritabanı üzerinde hesaplandı; model hiç çağrılmadı.",
    icon: FunctionSquare,
  },
  template: {
    label: "Model kapalı",
    note:
      "Yerel model erişilemedi ya da boş yanıt döndürdü. Getirilen kanıtlar geçerlidir; " +
      "yalnızca özet cümle modelden gelmedi.",
    icon: AlertTriangle,
  },
  refusal: {
    label: "Kanıt yok",
    note: "Sorgu süzgeçlerini sağlayan kayıt bulunamadı; uydurma yanıt üretilmedi.",
    icon: CircleSlash,
  },
};

// ⚠️ `source` tip düzeyinde `string`e genişliyor: backend yeni bir kaynak
// türü eklediğinde arayüz derlenmeye devam etmeli. Sözlükte bulunmayan bir
// değerde `undefined` render etmek beyaz ekran verirdi.
const BILINMEYEN = {
  label: "Kaynak bilinmiyor",
  note: "Yanıtın hangi katmanda üretildiği bildirilmedi.",
  icon: CircleSlash,
} as const;

export function GroundingNotice({ answer }: { answer: AnswerBlock }) {
  const kaynak = SOURCE_NOTES[answer.source] ?? BILINMEYEN;
  const KaynakIkonu = kaynak.icon;
  const dogrulandi = answer.is_grounded && answer.source === "model";

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-500">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex cursor-help items-center gap-1.5">
              <KaynakIkonu className="h-3.5 w-3.5" aria-hidden="true" />
              {kaynak.label}
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <p className="max-w-xs">{kaynak.note}</p>
          </TooltipContent>
        </Tooltip>

        {answer.model_name && <span>· {answer.model_name}</span>}

        {answer.latency_ms !== null && (
          <span className="tabular-nums">· {(answer.latency_ms / 1000).toFixed(1)} sn</span>
        )}

        {dogrulandi && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex cursor-help items-center gap-1">
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Kaynağa dayalı
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <p className="max-w-xs">
                Yanıttaki her sayı, getirilen kampanya kartlarının metninde bulundu.
              </p>
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      {answer.unverified_numbers.length > 0 && (
        <p className="flex items-start gap-1.5 rounded border border-danger-600/40 px-2 py-1.5 text-xs text-text-900">
          <AlertTriangle
            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger-600"
            aria-hidden="true"
          />
          <span>
            Şu değerler kaynak kartlarda bulunamadı ve <strong>doğrulanmamıştır</strong>:{" "}
            {answer.unverified_numbers.map((sayi) => sayi.value).join(" · ")}
          </span>
        </p>
      )}

      {answer.terminology_warnings.length > 0 && (
        <p className="flex items-start gap-1.5 rounded border border-warn-600/40 px-2 py-1.5 text-xs text-text-900">
          <AlertTriangle
            className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn-600"
            aria-hidden="true"
          />
          <span>
            Üretilen metinde konvansiyonel terim geçti:{" "}
            {answer.terminology_warnings
              .map((uyari) =>
                uyari.suggestion ? `“${uyari.term}” → “${uyari.suggestion}”` : `“${uyari.term}”`,
              )
              .join(" · ")}
          </span>
        </p>
      )}

      {answer.model_error && <p className="text-xs text-text-500">Model notu: {answer.model_error}</p>}
    </div>
  );
}
