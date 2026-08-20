import { useMemo, useState } from "react";

import { CampaignFilters, type FilterState } from "@/components/campaigns/CampaignFilters";
import { CampaignTable } from "@/components/campaigns/CampaignTable";
import { EvidenceDrawer } from "@/components/campaigns/EvidenceDrawer";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { useBanks } from "@/hooks/useBanks";
import { useCampaigns } from "@/hooks/useCampaigns";
import type { CampaignQuery } from "@/types/api";

const PAGE_SIZE = 25;
const EMPTY_FILTERS: FilterState = { banks: [], status: "all", q: "" };

export function CampaignsPage() {
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [sort, setSort] = useState<NonNullable<CampaignQuery["sort"]>>("title");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [drawerCampaignId, setDrawerCampaignId] = useState<number | null>(null);

  const { data: banks } = useBanks();

  const query = useMemo<CampaignQuery>(
    () => ({
      bank: filters.banks.length > 0 ? filters.banks : undefined,
      status: filters.status === "all" ? undefined : filters.status,
      q: filters.q || undefined,
      sort,
      order,
      page,
      page_size: PAGE_SIZE,
    }),
    [filters, sort, order, page],
  );

  const { data, isLoading, isError, error, refetch } = useCampaigns(query);

  const handleFiltersChange = (next: FilterState) => {
    setFilters(next);
    setPage(1);
  };

  const handleSortChange = (field: NonNullable<CampaignQuery["sort"]>) => {
    if (field === sort) {
      setOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSort(field);
      setOrder("asc");
    }
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-text-900">Kampanya Kataloğu</h1>
        <p className="mt-1 text-sm text-text-500">
          10 katılım bankasının kamuya açık kampanyaları — arama, filtre ve kanıt çekmecesiyle.
        </p>
      </div>

      <CampaignFilters banks={banks ?? []} value={filters} onChange={handleFiltersChange} />

      {isLoading && <LoadingState variant="table" />}

      {isError && <ErrorState error={error} onRetry={() => void refetch()} />}

      {!isLoading && !isError && data && data.items.length === 0 && (
        <EmptyState onClear={() => handleFiltersChange(EMPTY_FILTERS)} />
      )}

      {!isLoading && !isError && data && data.items.length > 0 && (
        <CampaignTable
          items={data.items}
          sort={sort}
          order={order}
          onSortChange={handleSortChange}
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          totalPages={data.total_pages}
          onPageChange={setPage}
          onRowClick={(campaign) => setDrawerCampaignId(campaign.id)}
        />
      )}

      <EvidenceDrawer campaignId={drawerCampaignId} onClose={() => setDrawerCampaignId(null)} />
    </div>
  );
}
