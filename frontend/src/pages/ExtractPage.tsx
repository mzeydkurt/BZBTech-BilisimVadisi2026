import { useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { ExtractedFieldsTable } from "@/components/extract/ExtractedFieldsTable";
import { ExtractForm } from "@/components/extract/ExtractForm";
import { LogicViolationsSection } from "@/components/extract/LogicViolationsSection";
import { RejectedFieldsSection } from "@/components/extract/RejectedFieldsSection";
import { taxonomyLabel } from "@/lib/taxonomy";
import { useExtract } from "@/hooks/useExtract";
import type { ExtractMode, ExtractResponse } from "@/types/api";


/**
 * Hangi yöntem kaç alan üretti — BİRLEŞTİRMEDEN ÖNCE.
 *
 * ⚠️ Tablodaki `fields` birleştirme sonucudur: aynı alanı hem kural hem model
 * bulduğunda kural kazanır (`METHOD_PRIORITY`) ve model satırı kaybolur.
 * Hibritte model ayrıca kuralın çözdüğü alanları HİÇ DENEMEZ. İkisi bir araya
 * gelince tabloda yalnızca "kural" görünüyor ve model hiç çalışmamış gibi
 * duruyordu.
 */
function MethodSummary({ data }: { data: ExtractResponse }) {
  const dokum = Object.entries(data.method_summary ?? {});
  if (dokum.length === 0) return null;

  const etiket: Record<string, string> = {
    rule: "kural",
    llm: "model",
    table: "tablo",
  };
  const atlanan = data.llm_skipped_fields ?? [];

  return (
    <div className="mt-2 rounded border border-border bg-neutral-50 p-2 text-xs text-text-700">
      <span className="text-text-500">Birleştirmeden önce: </span>
      {dokum.map(([yontem, adet], i) => (
        <span key={yontem}>
          {i > 0 && " · "}
          <span className="font-medium">{etiket[yontem] ?? yontem}</span> {adet} alan
        </span>
      ))}
      {atlanan.length > 0 && (
        <p className="mt-1 text-text-500">
          Kural {atlanan.length} alanı zaten çözdüğü için modele sorulmadı; model
          yalnızca kalan alanlarda çalıştı. Tabloda aynı alanı ikisi de bulduysa
          kural gösterilir.
        </p>
      )}
    </div>
  );
}

export function ExtractPage() {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<ExtractMode>("hybrid");

  const mutation = useExtract();

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Canlı Çıkarım Laboratuvarı</h1>
        <p className="mt-1 text-sm text-text-500">
          Bir kampanya metni verin; sistemin neyi kabul edip neyi reddettiğini görün.
        </p>
      </div>

      <ExtractForm
        text={text}
        onTextChange={setText}
        mode={mode}
        onModeChange={setMode}
        isPending={mutation.isPending}
        onSubmit={() => mutation.mutate({ text, mode })}
      />

      {mutation.isPending && <LoadingState variant="table" />}

      {mutation.isError && <ErrorState error={mutation.error} title="Çıkarım yapılamadı" />}

      {mutation.isSuccess && (
        <div className="space-y-4">
          {mutation.data.summary && (
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-sm text-text-900">{mutation.data.summary}</p>
            </div>
          )}

          <section>
            <h2 className="text-sm font-semibold text-text-900">Çıkarılan Alanlar</h2>
            <div className="mt-2">
              <ExtractedFieldsTable fields={mutation.data.fields} />
            </div>
            <MethodSummary data={mutation.data} />
          </section>

          {Object.keys(mutation.data.labels).length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-text-900">Etiketler</h2>
              <div className="mt-2 space-y-2">
                {Object.entries(mutation.data.labels).map(([axis, values]) => (
                  <div key={axis} className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium uppercase tracking-wide text-text-500">
                      {axis}
                    </span>
                    {values.map((value) => (
                      <span
                        key={value}
                        className="rounded border border-border px-1.5 py-0.5 text-xs text-text-700"
                      >
                        {taxonomyLabel(value)}
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            </section>
          )}

          <RejectedFieldsSection items={mutation.data.rejected} />
          <LogicViolationsSection violations={mutation.data.logic_violations} />

          <p className="text-xs text-text-500">
            Model: {mutation.data.model.name} ({mutation.data.model.license},{" "}
            {mutation.data.model.local ? "yerel" : "uzak"}) · Süre: {mutation.data.latency_ms} ms
          </p>
        </div>
      )}
    </div>
  );
}
