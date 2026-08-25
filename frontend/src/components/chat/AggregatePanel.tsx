import type { AggregateBlock } from "@/types/api";

/**
 * Toplama sorusunun HESABINI gösterir.
 *
 * Toplama bloğu backend'de hesaplanıyor ama arayüzde hiç gösterilmiyordu;
 * bilgi yalnızca yanıt cümlesinin içinde kalıyordu. "Her bankanın kaç
 * kampanyası var" sorusunun yanıtı bir CÜMLE değil, bir DÖKÜMDÜR.
 *
 * ⚠️ Sıfır sayılı bankalar gizlenmez. "Veri yok" bilgisi de bir bulgudur
 * (CLAUDE.md) ve rakip analizinde en çok işe yarayan bulgudur.
 *
 * ⚠️ Yokluk sorusunun yanıtı `banks_with` DEĞİL `banks_without`tur. İki küme
 * görsel olarak da ayrı gösterilir; karıştırmak yanıtı tersine çevirir.
 */
export function AggregatePanel({ data }: { data: AggregateBlock | null }) {
  if (!data) return null;

  const dokum = Object.entries(data.by_bank ?? {});
  const yok = data.banks_without ?? [];
  const var_ = data.banks_with ?? [];
  const kumeVar = data.kind === "absence" || data.kind === "count_banks";

  if (dokum.length === 0 && !kumeVar) return null;

  return (
    <section className="mt-3 rounded border border-border bg-neutral-50 p-3">
      <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-500">
        Hesap
      </h4>

      {kumeVar && (
        <div className="mb-3 space-y-2 text-sm">
          {/* Yokluk sorusunun ASIL yanıtı; önce ve vurgulu gösterilir. */}
          <div>
            <span className="font-medium text-text-900">
              Kaydı olmayan ({yok.length})
            </span>
            <p className="text-text-700">{yok.length > 0 ? yok.join(", ") : "—"}</p>
          </div>
          <div>
            <span className="text-text-500">Kaydı olan ({var_.length})</span>
            <p className="text-text-700">{var_.length > 0 ? var_.join(", ") : "—"}</p>
          </div>
        </div>
      )}

      {dokum.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-text-500">
                <th className="pb-1 pr-3 font-medium">Banka</th>
                <th className="pb-1 font-medium">Kayıt</th>
              </tr>
            </thead>
            <tbody>
              {dokum.map(([banka, adet]) => (
                <tr key={banka} className="border-t border-border">
                  <td className="py-1 pr-3 text-text-900">{banka}</td>
                  <td className={adet === 0 ? "py-1 text-text-500" : "py-1 text-text-900"}>
                    {adet}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.total > 0 && (
        <p className="mt-2 text-xs text-text-500">
          Toplam {data.total} kayıt üzerinden hesaplandı.
          {data.without_value > 0 && kumeVar === false
            ? ` ${data.without_value} kayıtta bu alan yok.`
            : ""}
        </p>
      )}
    </section>
  );
}
