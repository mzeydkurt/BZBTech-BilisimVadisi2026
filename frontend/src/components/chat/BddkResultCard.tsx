import { Link } from "react-router-dom";

import type { ChatBddkBlock } from "@/types/api";

export function BddkResultCard({ bddk }: { bddk: ChatBddkBlock }) {
  const params = new URLSearchParams({
    tab: "bddk",
    asset_type: bddk.asset_type,
    asset_value: String(bddk.asset_value_try),
    autorun: "1",
  });
  if (bddk.energy_class) params.set("energy_class", bddk.energy_class);
  if (bddk.first_home != null) params.set("first_home", bddk.first_home ? "true" : "false");

  return (
    <div className="mt-3 rounded-lg border border-border bg-surface px-3 py-2.5">
      <p className="text-[11px] text-text-500">BDDK limiti</p>
      <p className="mt-0.5 text-sm font-medium text-text-900">
        {bddk.value_band_label ?? bddk.asset_type}
      </p>
      <ul className="mt-2 space-y-1 text-xs text-text-500">
        {bddk.max_financing_ratio_pct != null && (
          <li>Azami oran: %{bddk.max_financing_ratio_pct}</li>
        )}
        {bddk.max_financing_amount_try != null && (
          <li>Azami tutar: {bddk.max_financing_amount_try} ₺</li>
        )}
        {bddk.max_allowed_term_months != null && (
          <li>Azami vade: {bddk.max_allowed_term_months} ay</li>
        )}
        {!bddk.is_financing_allowed && (
          <li className="text-danger-600">Bu değerde finansman izin verilmiyor.</li>
        )}
        {bddk.legal_reference && <li>Dayanak: {bddk.legal_reference}</li>}
      </ul>
      <Link
        to={`/simulator?${params.toString()}`}
        className="mt-2 inline-block text-[11px] font-medium text-brand-700 hover:text-brand-900"
      >
        BDDK sekmesinde hesapla →
      </Link>
    </div>
  );
}
