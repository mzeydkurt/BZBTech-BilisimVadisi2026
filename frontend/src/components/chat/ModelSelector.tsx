import { useQuery } from "@tanstack/react-query";
import { Cloud, HardDrive } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import type { ChatModelOption } from "@/types/api";

interface ModelSelectorProps {
  /** Seçili model anahtarı; `null` ise sunucunun yapılandırdığı kullanılır. */
  value: string | null;
  onChange: (modelId: string | null) => void;
}

/** Sunucu yapılandırmasını kullan — açık bir seçim yapılmadığında. */
const SUNUCU_VARSAYILANI = "__sunucu__";

/**
 * Model seçici.
 *
 * ⚠️ SEÇİM İSTEK BAŞINADIR, `.env` YAZILMAZ. Bir kullanıcının tercihi tüm
 * kurumun yapılandırmasını değiştirmemeli — hele jüri demosu sırasında.
 *
 * ⚠️ ERİŞİLEMEYEN MODEL LİSTEDEN GİZLENMEZ, DEVRE DIŞI GÖSTERİLİR. Gizlemek
 * "böyle bir seçenek yok" izlenimi verir; oysa yerel model kapalı ağ
 * gösteriminin kanıtı ve Ollama açıldığında seçilebilir hâle gelir.
 *
 * ⚠️ Bulut/yerel ayrımı ikonla gösterilir ama **robot/AI ikonu
 * kullanılmaz** (CLAUDE.md).
 */
export function ModelSelector({ value, onChange }: ModelSelectorProps) {
  const sorgu = useQuery({
    queryKey: ["chat-models"],
    queryFn: () => api.chatModels(),
    staleTime: 60_000,
  });

  if (sorgu.isError) {
    // ⚠️ Model listesi alınamazsa sohbet ÇALIŞMAYA DEVAM EDER; sunucunun
    // yapılandırdığı model kullanılır. Seçici bir kolaylıktır, zorunluluk değil.
    return (
      <span className="text-xs text-text-500">Model listesi alınamadı; sunucu ayarı geçerli.</span>
    );
  }

  const secenekler: ChatModelOption[] = sorgu.data?.items ?? [];
  const etkin = sorgu.data?.active_id;
  const secili = value ?? SUNUCU_VARSAYILANI;
  const seciliSecenek = secenekler.find((secenek) => secenek.id === value);

  return (
    <div className="flex items-center gap-1.5">
      <Select
        value={secili}
        onValueChange={(sonraki) =>
          onChange(sonraki === SUNUCU_VARSAYILANI ? null : sonraki)
        }
        disabled={sorgu.isPending}
      >
        <SelectTrigger id="sohbet-model" className="h-8 w-[230px]" aria-label="Yanıt modeli">
          <SelectValue placeholder="Model" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={SUNUCU_VARSAYILANI}>
            Sunucu ayarı{etkin ? ` (${etkin})` : ""}
          </SelectItem>
          {secenekler.map((secenek) => (
            <SelectItem
              key={secenek.id}
              value={secenek.id}
              disabled={!secenek.available}
            >
              {secenek.label}
              {!secenek.available && " — erişilemiyor"}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {seciliSecenek && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex cursor-help items-center text-text-500">
              {seciliSecenek.is_local ? (
                <HardDrive className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <Cloud className="h-3.5 w-3.5" aria-hidden="true" />
              )}
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <p className="max-w-xs">
              {seciliSecenek.note ?? seciliSecenek.label}
              {seciliSecenek.is_local
                ? " Kapalı ağda çalışır."
                : " Dış ağ bağlantısı gerektirir."}
            </p>
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}
