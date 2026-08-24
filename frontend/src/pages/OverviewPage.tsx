import { Activity, Building2, Calendar, Clock, LayoutList, Leaf, TimerOff } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { StatCard } from "@/components/common/StatCard";
import { BankCoverageTable } from "@/components/overview/BankCoverageTable";
import { CampaignsByBankChart } from "@/components/overview/CampaignsByBankChart";
import { SectorDistributionChart } from "@/components/overview/SectorDistributionChart";
import { StatusMixChart } from "@/components/overview/StatusMixChart";
import { TaxonomyDistributionChart } from "@/components/overview/TaxonomyDistributionChart";
import { useStats } from "@/hooks/useStats";
import { formatDateTime, formatNumber } from "@/lib/format";

export function OverviewPage() {
  const { data: stats, isLoading, isError, error, refetch } = useStats();

  if (isLoading) {
    return <LoadingState variant="cards" />;
  }

  if (isError) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  if (!stats) return null;

  const greenPct =
    stats.total_campaigns > 0
      ? (stats.green_campaigns_count / stats.total_campaigns) * 100
      : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-text-900">Genel Bakış</h1>
          <p className="mt-1 text-sm text-text-500">
            10 katılım bankasının kamuya açık kampanya ve ürün verilerinin özeti.
          </p>
        </div>
        {stats.last_scrape_at && (
          <div className="rounded-lg border border-border bg-surface px-3 py-2 text-right">
            <p className="text-[11px] uppercase tracking-wide text-text-500">Son kazıma</p>
            <p className="text-xs font-medium text-text-900">
              {formatDateTime(stats.last_scrape_at)}
            </p>
          </div>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          label="Toplam Banka"
          value={stats.total_banks}
          icon={Building2}
          hint={`${formatNumber(stats.banks_with_data)} veri kaynağı zengin`}
          info="Sistemde tanımlı katılım bankası sayısı. Alt satır, kamuya açık verisi zengin olan bankaları gösterir."
        />
        <StatCard
          label="Toplam Kampanya"
          value={stats.total_campaigns}
          icon={LayoutList}
          info="Tüm bankalardan toplanmış kampanya kayıtlarının toplamı (aktif, yaklaşan, bitmiş ve tarihsiz)."
        />
        <StatCard
          label="Aktif Kampanya"
          value={stats.active_campaigns}
          icon={Activity}
          tone="active"
          info="Şu an yürürlükte olan kampanyalar: başlangıç tarihi geçmiş, bitiş tarihi henüz gelmemiş."
        />
        <StatCard
          label="Yaklaşan Kampanya"
          value={stats.upcoming_campaigns}
          icon={Calendar}
          tone="upcoming"
          info="Başlangıç tarihi henüz gelmemiş kampanyalar. Yakında yürürlüğe girecekler."
        />
        <StatCard
          label="Tarihsiz"
          value={stats.unknown_status_campaigns}
          icon={TimerOff}
          hint="Bitiş tarihi olmayan"
          tone="unknown"
          info="Kaynak sayfada başlangıç veya bitiş tarihi bulunamayan kampanyalar. Durum kesin hesaplanamaz."
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          label="Ürün"
          value={stats.products_total}
          info="Bankaların yayımladığı finansman, katılma hesabı ve benzeri ürün kayıtlarının sayısı."
        />
        <StatCard
          label="Oran Kaydı"
          value={stats.rates_total}
          info="Ürünlere bağlı kâr payı / getiri satırları. Aynı ürünün farklı vade veya para birimi için ayrı oranları olabilir; bu yüzden ürün sayısından fazla olabilir."
        />
        <StatCard
          label="Limit Kaydı"
          value={stats.limits_total}
          info="Ürünlere bağlı finansman limitleri (ör. azami tutar, LTV). Bir ürünün birden fazla limit satırı olabilir."
        />
        <StatCard
          label="Yeşil Finans"
          value={stats.green_campaigns_count}
          icon={Leaf}
          hint={`Toplamın %${greenPct.toFixed(1)}'i`}
          tone="active"
          info="Çevre / sürdürülebilirlik / yeşil finans temalı olarak sınıflandırılmış kampanya sayısı."
        />
        <Link
          to="/campaigns?status=active"
          className="block rounded-lg transition-opacity hover:opacity-90"
        >
          <StatCard
            label="Yakında Biten"
            value={stats.ending_soon_count}
            icon={Clock}
            hint="Aktif · ≤14 gün · katalogda aç"
            tone="upcoming"
            info="Aktif kampanyalar arasında bitiş tarihi 14 gün veya daha az kalanlar. Tıklayınca kampanya listesine gider."
          />
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <StatusMixChart
          active={stats.active_campaigns}
          upcoming={stats.upcoming_campaigns}
          expired={stats.expired_campaigns}
          unknown={stats.unknown_status_campaigns}
        />
        <BankCoverageTable data={stats.active_by_bank} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <CampaignsByBankChart data={stats.campaigns_by_bank} />
        <SectorDistributionChart data={stats.sector_distribution} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <TaxonomyDistributionChart title="Hedef Kitle" data={stats.audience_distribution} />
        <TaxonomyDistributionChart title="Fayda Türü" data={stats.benefit_distribution} />
      </div>
    </div>
  );
}
