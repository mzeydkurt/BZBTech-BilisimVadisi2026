import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { RetrievalReport } from "@/types/api";

/**
 * Erişim şeffaflık şeridi.
 *
 * ⚠️ "8 sonuç bulundu" ile "2 kayıt kâr payı eşiğine takıldı, 8 sonuç kaldı"
 * kullanıcı için aynı şey değildir. Neyin elendiğini görmeyen kullanıcı, boş
 * ya da kısa bir listeyi "banka bu kampanyayı yapmıyor" diye okur.
 */
export function RetrievalStrip({ report }: { report: RetrievalReport }) {
  const kanallar: string[] = [];
  if (report.lexical_used) {
    kanallar.push("sözcüksel");
  }
  if (report.semantic_used) {
    kanallar.push("anlamsal");
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-neutral-50 px-3 py-2 text-xs text-text-500">
      <span className="tabular-nums">
        {report.corpus_size} karttan <strong className="text-text-900">{report.returned}</strong>{" "}
        getirildi
      </span>

      {kanallar.length > 0 && <span>· kanal: {kanallar.join(" + ")}</span>}

      {report.total_rejected > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help underline decoration-dotted underline-offset-2">
              · {report.total_rejected} kayıt süzgeçlere takıldı
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <ul className="max-w-xs space-y-0.5">
              {report.rejected.map((eleme) => (
                <li key={eleme.filter} className="tabular-nums">
                  {eleme.label}: {eleme.count}
                </li>
              ))}
            </ul>
          </TooltipContent>
        </Tooltip>
      )}

      <span className="tabular-nums">· {report.elapsed_ms} ms</span>

      {report.semantic_note && (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help underline decoration-dotted underline-offset-2">
              · anlamsal kanal kapalı
            </span>
          </TooltipTrigger>
          <TooltipContent>
            <p className="max-w-xs">{report.semantic_note}</p>
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}
