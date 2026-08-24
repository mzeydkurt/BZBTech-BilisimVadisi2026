import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { CampaignFilters, type FilterState } from "@/components/campaigns/CampaignFilters";
import { CampaignTable } from "@/components/campaigns/CampaignTable";
import { EvidenceDrawer } from "@/components/campaigns/EvidenceDrawer";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { LoadingState } from "@/components/common/LoadingState";
import { useBanks } from "@/hooks/useBanks";
import { useCampaigns } from "@/hooks/useCampaigns";
import type { CampaignQuery, CampaignStatus } from "@/types/api";

const PAGE_SIZE = 25;
const STATUS_VALUES: CampaignStatus[] = ["active", "upcoming", "expired", "unknown"];

const EMPTY_FILTERS: FilterState = {
  banks: [],
  status: "all",
  q: "",
  includeExpired: false,
  sector: "all",
  productType: "all",
  segment: "all",
};

function filtersFromSearch(params: URLSearchParams): FilterState {
  const raw = params.get("status");
  const status =
    raw && (STATUS_VALUES as string[]).includes(raw) ? (raw as CampaignStatus) : "all";
  return { ...EMPTY_FILTERS, status };
}

function idFromSearch(params: URLSearchParams): number | null {
  const raw = params.get("id");
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function CampaignsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState<FilterState>(() => filtersFromSearch(searchParams));
  const [sort, setSort] = useState<NonNullable<CampaignQuery["sort"]>>("title");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  const [drawerCampaignId, setDrawerCampaignId] = useState<number | null>(() =>
    idFromSearch(searchParams),
  );

  // Geriye dönük uyum: /campaigns?id=123 → EvidenceDrawer açılır.
  useEffect(() => {
    const fromQuery = idFromSearch(searchParams);
    if (fromQuery !== null) setDrawerCampaignId(fromQuery);
  }, [searchParams]);

  const { data: banks } = useBanks();

  const query = useMemo<CampaignQuery>(
    () => ({
      bank: filters.banks.length > 0 ? filters.banks : undefined,
      status: filters.status === "all" ? undefined : filters.status,
      q: filters.q || undefined,
      include_expired: filters.includeExpired || undefined,
      sector: filters.sector === "all" ? undefined : filters.sector,
      product_type: filters.productType === "all" ? undefined : filters.productType,
      segment: filters.segment === "all" ? undefined : filters.segment,
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

  const handleDrawerClose = () => {
    setDrawerCampaignId(null);
    if (searchParams.has("id")) {
      const next = new URLSearchParams(searchParams);
      next.delete("id");
      setSearchParams(next, { replace: true });
    }
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

      <EvidenceDrawer campaignId={drawerCampaignId} onClose={handleDrawerClose} />
    </div>
  );
}
