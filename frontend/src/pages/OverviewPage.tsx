import { Activity, Building2, Calendar, LayoutList, TimerOff } from "lucide-react";

import { CampaignsByBankChart } from "@/components/overview/CampaignsByBankChart";
import { RadarScoreChart } from "@/components/overview/RadarScoreChart";
import { SectorDistributionChart } from "@/components/overview/SectorDistributionChart";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { StatCard } from "@/components/common/StatCard";
import { useStats } from "@/hooks/useStats";
import { formatDateTime, formatNumber, formatPercent } from "@/lib/format";

export function OverviewPage() {
  const { data: stats, isLoading, isError, error, refetch } = useStats();

  if (isLoading) {
    return <LoadingState variant="cards" />;
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  if (!stats) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-900">Genel Bakış</h1>
          <p className="mt-1 text-sm text-text-500">
            10 katılım bankasının kamuya açık kampanya ve ürün verilerinin özeti.
          </p>
        </div>
        {stats.last_scrape_at && (
          <p className="text-xs text-text-500">
            Son güncelleme: {formatDateTime(stats.last_scrape_at)}
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          label="Toplam Banka"
          value={stats.total_banks}
          icon={Building2}
          hint={`${formatNumber(stats.banks_with_data)} veri kaynağı zengin`}
        />
        <StatCard label="Toplam Kampanya" value={stats.total_campaigns} icon={LayoutList} />
        <StatCard
          label="Aktif Kampanya"
          value={stats.active_campaigns}
          icon={Activity}
          tone="active"
        />
        <StatCard
          label="Yaklaşan Kampanya"
          value={stats.upcoming_campaigns}
          icon={Calendar}
          tone="upcoming"
        />
        <StatCard
          label="Süresi Dolan"
          value={stats.expired_campaigns}
          icon={TimerOff}
          tone="expired"
        />
      </div>

      {/* ⚠️ `unknown` durumu `expired`dan AYRIDIR, gizlenmez. */}
      <div className="rounded-lg border border-dashed border-warn-600/40 bg-surface px-4 py-2 text-sm text-text-500">
        <span className="font-medium text-warn-600">{formatNumber(stats.unknown_status_campaigns)}</span>{" "}
        kampanyada tarih bilgisi bulunmuyor — bunlar &quot;süresi dolmuş&quot; SAYILMAZ, kaynak
        sayfada tarih hiç belirtilmemiş demektir.
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Ürün" value={stats.products_total} />
        <StatCard label="Oran Kaydı" value={stats.rates_total} />
        <StatCard label="Limit Kaydı" value={stats.limits_total} />
        <div className="rounded-lg border border-border bg-surface p-4">
          <span className="text-sm text-text-500">Yapay Zekâ Kapsamı</span>
          <p className="tabular mt-2 text-2xl font-semibold text-text-900">
            {formatPercent(stats.ai_coverage_pct, { decimals: 1 })}
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <CampaignsByBankChart data={stats.campaigns_by_bank} />
          <SectorDistributionChart data={stats.sector_distribution} />
        </div>
        <RadarScoreChart scores={stats.radar_scores} />
      </div>
    </div>
  );
}
