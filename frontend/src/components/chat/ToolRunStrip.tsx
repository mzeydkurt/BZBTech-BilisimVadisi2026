import type { ChatToolRun } from "@/types/api";

const TOOL_LABEL: Record<string, string> = {
  finansman_teklif: "Finansman simülasyonu",
  bddk_limit: "BDDK limit kontrolü",
  katilma_getiri: "Katılma getirisi",
  urun_karsilastir: "Ürün karşılaştırması",
};

export function ToolRunStrip({ runs }: { runs: ChatToolRun[] }) {
  if (!runs.length) return null;
  return (
    <div className="mt-2 space-y-1">
      {runs.map((r, i) => (
        <p
          key={`${r.tool}-${i}`}
          className="text-[11px] leading-relaxed text-text-500"
        >
          <span className="font-medium text-text-700">
            {TOOL_LABEL[r.tool] ?? r.tool}
          </span>
          {" · "}
          {r.summary}
          {r.elapsed_ms > 0 ? ` · ${r.elapsed_ms} ms` : ""}
        </p>
      ))}
    </div>
  );
}
