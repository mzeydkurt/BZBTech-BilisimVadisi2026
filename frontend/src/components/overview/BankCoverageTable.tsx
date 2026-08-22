import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { BankCoverage } from "@/types/api";

/** Banka bazında aktif / toplam kampanya kapsaması. */
export function BankCoverageTable({ data }: { data: BankCoverage[] }) {
  const rows = [...data].sort((a, b) => b.active - a.active || b.total - a.total);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Banka Kapsaması</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-500">
                <th className="pb-2 font-medium">Banka</th>
                <th className="pb-2 text-right font-medium">Aktif</th>
                <th className="pb-2 text-right font-medium">Toplam</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.bank_code} className="border-b border-border/60 last:border-0">
                  <td className="py-2 text-text-900">{row.bank_name}</td>
                  <td className="tabular py-2 text-right text-brand-500">
                    {formatNumber(row.active)}
                  </td>
                  <td className="tabular py-2 text-right text-text-500">
                    {formatNumber(row.total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
