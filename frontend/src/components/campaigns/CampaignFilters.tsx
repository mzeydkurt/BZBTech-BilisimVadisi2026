import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatNumber } from "@/lib/format";
import {
  PRODUCT_TYPE_FILTER_OPTIONS,
  SEGMENT_FILTER_OPTIONS,
  SECTOR_FILTER_OPTIONS,
  taxonomyLabel,
} from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { Bank, CampaignStatus } from "@/types/api";

export interface FilterState {
  banks: string[];
  status: CampaignStatus | "all";
  q: string;
  /** Varsayılan false: süresi kesin dolmuş kampanyalar gizlenir (KAPI 5). */
  includeExpired: boolean;
  sector: string | "all";
  productType: string | "all";
  segment: string | "all";
}

interface CampaignFiltersProps {
  banks: Bank[];
  value: FilterState;
  onChange: (next: FilterState) => void;
}

const STATUS_OPTIONS: { value: CampaignStatus | "all"; label: string }[] = [
  { value: "all", label: "Tüm durumlar" },
  { value: "active", label: "Aktif" },
  { value: "upcoming", label: "Yaklaşan" },
  { value: "expired", label: "Süresi Doldu" },
  { value: "unknown", label: "Tarih Yok" },
];

const ALL = "all";

export function CampaignFilters({ banks, value, onChange }: CampaignFiltersProps) {
  // Arama kutusu her tuş vuruşunda istek atmasın diye geciktirilir.
  const [searchDraft, setSearchDraft] = useState(value.q);

  useEffect(() => {
    setSearchDraft(value.q);
  }, [value.q]);

  useEffect(() => {
    if (searchDraft === value.q) return;
    const timer = window.setTimeout(() => onChange({ ...value, q: searchDraft }), 300);
    return () => window.clearTimeout(timer);
  }, [searchDraft, value, onChange]);

  const toggleBank = (code: string) => {
    const next = value.banks.includes(code)
      ? value.banks.filter((item) => item !== code)
      : [...value.banks, code];
    onChange({ ...value, banks: next });
  };

  const hasActiveFilter =
    value.banks.length > 0 ||
    value.status !== ALL ||
    value.q !== "" ||
    value.includeExpired ||
    value.sector !== ALL ||
    value.productType !== ALL ||
    value.segment !== ALL;

  const clearFilters = () =>
    onChange({
      banks: [],
      status: "all",
      q: "",
      includeExpired: false,
      sector: ALL,
      productType: ALL,
      segment: ALL,
    });

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[240px] flex-1">
          <label htmlFor="campaign-search" className="mb-1 block text-sm text-text-500">
            Ara
          </label>
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-500"
              aria-hidden="true"
            />
            <Input
              id="campaign-search"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="Kampanya başlığı veya açıklaması"
              className="pl-9"
            />
          </div>
        </div>

        <div className="w-48">
          <label htmlFor="campaign-status" className="mb-1 block text-sm text-text-500">
            Durum
          </label>
          <Select
            value={value.status}
            onValueChange={(next) =>
              onChange({ ...value, status: next as CampaignStatus | "all" })
            }
          >
            <SelectTrigger id="campaign-status">
              <SelectValue placeholder="Tüm durumlar" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-48">
          <label htmlFor="campaign-sector" className="mb-1 block text-sm text-text-500">
            Sektör
          </label>
          <Select
            value={value.sector}
            onValueChange={(next) => onChange({ ...value, sector: next })}
          >
            <SelectTrigger id="campaign-sector">
              <SelectValue placeholder="Tüm sektörler" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm sektörler</SelectItem>
              {SECTOR_FILTER_OPTIONS.map((slug) => (
                <SelectItem key={slug} value={slug}>
                  {taxonomyLabel(slug)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-48">
          <label htmlFor="campaign-product-type" className="mb-1 block text-sm text-text-500">
            Ürün türü
          </label>
          <Select
            value={value.productType}
            onValueChange={(next) => onChange({ ...value, productType: next })}
          >
            <SelectTrigger id="campaign-product-type">
              <SelectValue placeholder="Tüm ürün türleri" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm ürün türleri</SelectItem>
              {PRODUCT_TYPE_FILTER_OPTIONS.map((slug) => (
                <SelectItem key={slug} value={slug}>
                  {taxonomyLabel(slug)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-40">
          <label htmlFor="campaign-segment" className="mb-1 block text-sm text-text-500">
            Segment
          </label>
          <Select
            value={value.segment}
            onValueChange={(next) => onChange({ ...value, segment: next })}
          >
            <SelectTrigger id="campaign-segment">
              <SelectValue placeholder="Tüm segmentler" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Tüm segmentler</SelectItem>
              {SEGMENT_FILTER_OPTIONS.map((slug) => (
                <SelectItem key={slug} value={slug}>
                  {taxonomyLabel(slug)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2 pb-2">
          <input
            id="campaign-include-expired"
            type="checkbox"
            checked={value.includeExpired}
            onChange={(event) => onChange({ ...value, includeExpired: event.target.checked })}
            className="h-4 w-4 rounded-sm border-border"
          />
          <label htmlFor="campaign-include-expired" className="text-sm text-text-500">
            Süresi dolmuşları da göster
          </label>
        </div>

        {hasActiveFilter && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            <X className="h-4 w-4" aria-hidden="true" />
            Temizle
          </Button>
        )}
      </div>

      <fieldset className="mt-4">
        <legend className="mb-2 text-sm text-text-500">Bankalar</legend>
        <div className="flex flex-wrap gap-2">
          {banks.map((bank) => {
            const selected = value.banks.includes(bank.code);
            const disabled = bank.campaign_count === 0;

            return (
              <button
                key={bank.code}
                type="button"
                onClick={() => toggleBank(bank.code)}
                disabled={disabled}
                aria-pressed={selected}
                title={
                  disabled
                    ? (bank.notes ?? "Bu bankanın kamuya açık kampanya sayfası bulunmuyor.")
                    : undefined
                }
                className={cn(
                  "inline-flex items-center gap-2 rounded-sm border px-2.5 py-1 text-sm",
                  "transition-colors duration-150",
                  selected
                    ? "border-brand-700 bg-teal-100 text-brand-900"
                    : "border-border bg-surface text-text-900 hover:border-text-500",
                  disabled && "cursor-not-allowed opacity-50 hover:border-border",
                )}
              >
                {bank.name}
                <span className="tabular text-xs text-text-500">
                  {formatNumber(bank.campaign_count)}
                </span>
              </button>
            );
          })}
        </div>
      </fieldset>
    </div>
  );
}
