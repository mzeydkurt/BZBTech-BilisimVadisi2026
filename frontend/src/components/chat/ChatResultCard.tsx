import { ExternalLink } from "lucide-react";

import { formatPercent } from "@/lib/format";
import type { ChatResultItem } from "@/types/api";

export function ChatResultCard({ item }: { item: ChatResultItem }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-text-500">{item.bank_name}</p>
          <p className="text-sm font-semibold text-text-900">{item.title}</p>
        </div>
        {/* ⚠️ Bu alan gerçek `float`tur, Decimal string DEĞİL — doğrudan formatlanır. */}
        {item.profit_rate_pct !== null && (
          <span className="tabular shrink-0 text-sm font-medium text-brand-700">
            {formatPercent(item.profit_rate_pct)}
          </span>
        )}
      </div>

      {item.summary && <p className="mt-2 text-sm text-text-900">{item.summary}</p>}

      {item.evidence_text && (
        <p className="mt-2 text-xs text-text-500">“{item.evidence_text}”</p>
      )}

      {item.source_url && (
        <a
          href={item.source_url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-brand-700 hover:text-brand-900"
        >
          Kaynağı gör
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      )}
    </div>
  );
}
