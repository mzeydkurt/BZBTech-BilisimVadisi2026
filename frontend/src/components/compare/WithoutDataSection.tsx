import type { RankedProduct } from "@/types/api";

/**
 * ⚠️ `without_data` ASLA gizlenmez. Ölçütün alanı `null` olan ürün sıralamaya
 * karışmaz ama listeden düşürülürse o banka "yokmuş" gibi görünür — bu yüzden
 * ayrı, her zaman görünür bir bölümde `missing_reason` ile gösterilir.
 */
export function WithoutDataSection({ items }: { items: RankedProduct[] }) {
  if (items.length === 0) return null;

  return (
    <div className="rounded-lg border border-dashed border-border bg-neutral-50 p-4">
      <h3 className="text-sm font-semibold text-text-500">
        Veri Yetersiz — {items.length} ürün sıralanamadı
      </h3>
      <ul className="mt-2 space-y-2">
        {items.map((item, index) => (
          <li key={`${item.product_id}-${index}`} className="text-sm">
            <span className="font-medium text-text-900">{item.product_name}</span>
            <span className="text-text-500"> ({item.bank_name})</span>
            {item.missing_reason && (
              <p className="text-xs text-text-500">{item.missing_reason}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
