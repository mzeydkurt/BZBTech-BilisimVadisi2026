import type { RejectedFieldOut } from "@/types/api";

/**
 * ⚠️ Sistemin neyi kabul etmediğini göstermek, kabul ettiklerine olan güveni
 * artırır — bu bölüm gizlenmez, jüri/kullanıcı demosunun en etkili parçasıdır.
 */
export function RejectedFieldsSection({ items }: { items: RejectedFieldOut[] }) {
  if (items.length === 0) return null;

  return (
    <section className="rounded-lg border border-dashed border-border bg-neutral-50 p-4">
      <h3 className="text-sm font-semibold text-text-500">Reddedilen Alanlar</h3>
      <ul className="mt-2 space-y-2">
        {items.map((item, index) => (
          <li key={`${item.field_name}-${index}`} className="text-sm">
            <span className="font-medium text-text-900">{item.field_name}</span>
            <span className="text-text-500"> — “{item.value}” ({item.method})</span>
            <p className="text-xs text-text-500">{item.reason}</p>
            {item.evidence && (
              <p className="text-xs text-text-400">Kanıt: “{item.evidence}”</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
