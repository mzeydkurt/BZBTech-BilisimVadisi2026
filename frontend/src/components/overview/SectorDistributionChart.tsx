import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { taxonomyLabel } from "@/lib/taxonomy";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { SectorCount } from "@/types/api";

const COLORS = [
  "var(--brand-700)",
  "var(--teal-500)",
  "var(--brand-500)",
  "#5b8f7a",
  "#8fb9a8",
  "#a8c9bd",
  "#c2d9d1",
  "#0f3d2e",
];

/** Sektör dağılımı — donut. `null` gelen sektörler gizlenmez, "Diğer" adıyla gösterilir. */
export function SectorDistributionChart({ data }: { data: SectorCount[] }) {
  const chartData = data
    .map((item) => ({
      name: item.sector ? taxonomyLabel(item.sector) : "Diğer",
      value: item.count,
    }))
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sektör Dağılımı</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={60}
                outerRadius={100}
                paddingAngle={1}
                isAnimationActive={false}
              >
                {chartData.map((entry, index) => (
                  <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value: number) => formatNumber(value)}
                contentStyle={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Sektör sayısı (~20) recharts'ın dahili legend'ını taşırıyordu;
            sabit yükseklikli kutunun içinde kalan, kendi 2 sütunlu grid'imiz. */}
        <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
          {chartData.map((entry, index) => (
            <li key={entry.name} className="flex items-center gap-1.5 text-xs text-text-500">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: COLORS[index % COLORS.length] }}
                aria-hidden="true"
              />
              <span className="truncate">{entry.name}</span>
              <span className="tabular ml-auto shrink-0 text-text-900">
                {formatNumber(entry.value)}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
