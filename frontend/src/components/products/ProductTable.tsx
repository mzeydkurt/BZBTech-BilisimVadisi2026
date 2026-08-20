import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { taxonomyLabel } from "@/lib/taxonomy";
import { RateTypeBadge } from "@/components/products/RateTypeBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatPercent, formatText } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ProductOut } from "@/types/api";

interface ProductGroup {
  parent: ProductOut;
  variants: ProductOut[];
}

/**
 * ⚠️ Liste düz gelir; varyantlar `parent_product_id` ile bağlıdır. Ana ürünün
 * `rates` dizisi çoğu zaman boştur — bu bir hata değildir, oranlar
 * varyantlarda durur. Ana satır asla gizlenmez.
 */
function groupByParent(products: ProductOut[]): ProductGroup[] {
  const parents = new Map<number, ProductGroup>();
  const orphanVariants: ProductOut[] = [];

  for (const product of products) {
    if (product.parent_product_id === null) {
      parents.set(product.id, { parent: product, variants: [] });
    }
  }

  for (const product of products) {
    if (product.parent_product_id !== null) {
      const group = parents.get(product.parent_product_id);
      if (group) {
        group.variants.push(product);
      } else {
        orphanVariants.push(product);
      }
    }
  }

  const groups = Array.from(parents.values());
  // Ana kaydı sayfalanmamış olabilir (limit sınırı); yetim varyantı da göster.
  for (const variant of orphanVariants) {
    groups.push({ parent: variant, variants: [] });
  }

  return groups;
}

function primaryRateCell(product: ProductOut) {
  if (product.rates.length === 0) {
    return <span className="text-text-400">—</span>;
  }

  return (
    <div className="flex flex-col gap-1">
      {product.rates.slice(0, 2).map((rate) => (
        <div key={rate.id} className="flex items-center gap-1.5">
          <RateTypeBadge rateType={rate.rate_type} />
          <span className="tabular text-text-900">
            {formatPercent(rate.profit_rate_pct)}
          </span>
        </div>
      ))}
      {product.rates.length > 2 && (
        <span className="text-xs text-text-400">+{product.rates.length - 2} oran</span>
      )}
    </div>
  );
}

export function ProductTable({ products }: { products: ProductOut[] }) {
  const groups = groupByParent(products);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead>Ürün</TableHead>
            <TableHead className="w-40">Banka</TableHead>
            <TableHead className="w-44">Tür</TableHead>
            <TableHead className="w-56">Oran</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((group) => (
            <ProductGroupRows key={group.parent.id} group={group} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ProductGroupRows({ group }: { group: ProductGroup }) {
  const { parent, variants } = group;

  return (
    <>
      <TableRow>
        <TableCell className="font-medium text-text-900">
          <Link to={`/products/${parent.id}`} className="hover:text-brand-700 hover:underline">
            {parent.name}
          </Link>
          {variants.length > 0 && (
            <span className="ml-2 text-xs font-normal text-text-500">
              {variants.length} varyant
            </span>
          )}
        </TableCell>
        <TableCell className="text-text-500">{formatText(parent.bank_name)}</TableCell>
        <TableCell className="text-text-500">
          {parent.product_type ? taxonomyLabel(parent.product_type) : "—"}
        </TableCell>
        <TableCell>{primaryRateCell(parent)}</TableCell>
        <TableCell>
          <Link
            to={`/products/${parent.id}`}
            className="inline-flex items-center justify-center text-text-500 hover:text-brand-700"
            aria-label={`${parent.name} detayını gör`}
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </TableCell>
      </TableRow>

      {variants.map((variant) => (
        <TableRow key={variant.id} className="bg-neutral-50/40">
          <TableCell className={cn("pl-8 text-text-900")}>
            <Link to={`/products/${variant.id}`} className="hover:text-brand-700 hover:underline">
              ↳ {formatText(variant.variant_label, variant.name)}
            </Link>
          </TableCell>
          <TableCell className="text-text-500">{formatText(variant.bank_name)}</TableCell>
          <TableCell className="text-text-500">
            {variant.product_type ? taxonomyLabel(variant.product_type) : "—"}
          </TableCell>
          <TableCell>{primaryRateCell(variant)}</TableCell>
          <TableCell>
            <Link
              to={`/products/${variant.id}`}
              className="inline-flex items-center justify-center text-text-500 hover:text-brand-700"
              aria-label={`${variant.name} detayını gör`}
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}
