import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { taxonomyLabel } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { CampaignCategory, TaxonomyAxis } from "@/types/api";

const SOURCE_LABELS: Record<string, string> = {
  url: "adres yolundan (bankanın verisi)",
  bank_category: "bankanın kendi etiketi",
  merchant: "marka eşleşmesi",
  keyword: "anahtar kelime",
  llm: "yapay zekâ çıkarımı",
};

/**
 * ⚠️ Düşük güvenli etiket GİZLENMEZ, ayrı gösterilir.
 *
 * Sektörü çıkarılamayan kampanyalara `genel` etiketi 0.30 güvenle yazılıyor.
 * Bunu diğerleriyle aynı biçimde göstermek "sınıflandırıldı" izlenimi verir;
 * gizlemek ise kampanyayı etiketsiz gösterir. İkisi de yanlış — soluk
 * gösterilir ve nedeni ipucunda yazar.
 */
const LOW_CONFIDENCE = 0.5;

interface CategoryBadgesProps {
  categories: CampaignCategory[];
  /** Gösterilecek eksen. Verilmezse tüm eksenler gösterilir. */
  axis?: TaxonomyAxis;
  /** En fazla kaç etiket gösterilsin; gerisi "+N" olarak özetlenir. */
  max?: number;
  className?: string;
}

/**
 * Kampanyanın taksonomi etiketlerini rozet olarak gösterir.
 *
 * Her rozetin ipucunda kanıt bulunur: etiket hangi kaynaktan ve hangi metinden
 * çıkarıldı. Kaynaksız etiket bankacılıkta kabul edilemez, bu yüzden kanıt
 * arayüzde de erişilebilir durur.
 */
export function CategoryBadges({
  categories,
  axis,
  max = 3,
  className,
}: CategoryBadgesProps) {
  const filtered = axis
    ? categories.filter((category) => category.axis === axis)
    : categories;

  if (filtered.length === 0) {
    // Sınıflandırma henüz çalıştırılmamış olabilir; boş göstermek yanıltır.
    return <span className="text-text-400">Sınıflandırılmadı</span>;
  }

  const shown = filtered.slice(0, max);
  const rest = filtered.length - shown.length;

  return (
    <div className={cn("flex flex-wrap items-center gap-1", className)}>
      {shown.map((category) => {
        const weak = Number(category.confidence) < LOW_CONFIDENCE;
        return (
          <Tooltip key={`${category.axis}-${category.value}`}>
            <TooltipTrigger asChild>
              <span
                className={cn(
                  "inline-flex items-center rounded border px-1.5 py-0.5 text-xs",
                  weak
                    ? "border-dashed border-border text-text-400"
                    : "border-border bg-surface-100 text-text-700",
                )}
              >
                {taxonomyLabel(category.value)}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <div className="max-w-xs space-y-1">
                <div>
                  Kaynak: {SOURCE_LABELS[category.source] ?? category.source} · güven{" "}
                  {Number(category.confidence).toFixed(2)}
                </div>
                {category.evidence && (
                  <div className="text-text-400">“{category.evidence}”</div>
                )}
                {weak && (
                  <div className="text-text-400">
                    Sektör çıkarılamadı; sonraki aşamada yeniden değerlendirilecek.
                  </div>
                )}
              </div>
            </TooltipContent>
          </Tooltip>
        );
      })}
      {rest > 0 && <span className="text-xs text-text-400">+{rest}</span>}
    </div>
  );
}
