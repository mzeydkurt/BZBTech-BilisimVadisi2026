import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { formatPercent } from "@/lib/format";
import type { ChatProductItem, ChatResultItem, ChatTopMatch } from "@/types/api";

/** Temiz kampanya kartı — teknik card_text / kanal dökümü yok. */
export function ChatResultCard({ item }: { item: ChatResultItem }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface p-3">
      <p className="text-[11px] text-text-500">{item.bank_name}</p>
      <p className="mt-0.5 text-sm font-medium leading-snug text-text-900 line-clamp-2">
        {item.title}
      </p>
      {item.summary && (
        <p className="mt-2 flex-1 text-xs leading-relaxed text-text-500 line-clamp-3">
          {item.summary}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:text-brand-900"
          >
            Kaynak
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        )}
        <Button asChild variant="secondary" size="sm" className="h-7 text-xs">
          <Link to={`/campaigns/${item.campaign_id}`}>Detay</Link>
        </Button>
      </div>
    </div>
  );
}

export function ChatProductCard({ item }: { item: ChatProductItem }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface p-3">
      <p className="text-[11px] text-text-500">{item.bank_name}</p>
      <p className="mt-0.5 text-sm font-medium leading-snug text-text-900 line-clamp-2">
        {item.product_name}
      </p>
      {item.profit_rate_pct !== null && (
        <p className="mt-2 text-sm text-brand-700">{formatPercent(item.profit_rate_pct)}</p>
      )}
      <div className="mt-auto pt-3">
        <Button asChild variant="secondary" size="sm" className="h-7 text-xs">
          <Link to={`/products/${item.product_id}`}>Detay</Link>
        </Button>
      </div>
    </div>
  );
}

/** top_matches için eşit boyutta öneri kutusu. */
export function ChatMatchCard({
  match,
  href,
}: {
  match: ChatTopMatch;
  href: string;
}) {
  return (
    <Link
      to={href}
      className="flex h-full min-h-[7.5rem] flex-col rounded-lg border border-border bg-surface px-3 py-2.5 transition-colors hover:border-brand-500"
    >
      {match.bank_name && (
        <p className="text-[11px] text-text-500">{match.bank_name}</p>
      )}
      <p className="mt-0.5 text-sm font-medium leading-snug text-text-900 line-clamp-2">
        {match.title}
      </p>
      {match.reason && (
        <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-500 line-clamp-3">
          {match.reason}
        </p>
      )}
    </Link>
  );
}
