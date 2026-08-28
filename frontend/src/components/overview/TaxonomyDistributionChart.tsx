import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import { taxonomyLabel } from "@/lib/taxonomy";
import type { TaxonomyCount } from "@/types/api";

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

interface TaxonomyDistributionChartProps {
  title: string;
  data: TaxonomyCount[];
  /** En fazla kaç dilim gösterilsin; kalanı “Diğer”de toplanır. */
  limit?: number;
}

/** Taksonomi ekseni dağılımı (hedef kitle / fayda). */
export function TaxonomyDistributionChart({
  title,
  data,
  limit = 8,
}: TaxonomyDistributionChartProps) {
  const sorted = [...data].filter((d) => d.count > 0).sort((a, b) => b.count - a.count);
  const top = sorted.slice(0, limit);
  const rest = sorted.slice(limit).reduce((sum, d) => sum + d.count, 0);
  const chartData = [
    ...top.map((item) => ({
      name: taxonomyLabel(item.value),
      value: item.count,
    })),
    ...(rest > 0 ? [{ name: "Diğer", value: rest }] : []),
  ];

  if (chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-8 text-center text-sm text-text-500">Henüz etiket yok.</p>
        </CardContent>
      </Card>
    );
  }

  const total = chartData.reduce((acc, d) => acc + d.value, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={60}
                outerRadius={95}
                paddingAngle={1.5}
                isAnimationActive={false}
              >
                {chartData.map((entry, index) => (
                  <Cell key={entry.name} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value: number) => [
                  `${formatNumber(value)} (${total > 0 ? ((value / total) * 100).toFixed(1) : 0}%)`,
                  "Kampanya",
                ]}
                contentStyle={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-3 border-t border-border/60 pt-3">
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 text-xs">
            {chartData.map((entry, index) => {
              const pct = total > 0 ? ((entry.value / total) * 100).toFixed(1) : "0";
              const color = COLORS[index % COLORS.length];
              return (
                <li
                  key={entry.name}
                  className="flex items-center justify-between gap-2 rounded bg-neutral-50 px-2.5 py-1.5 border border-border/40"
                >
                  <div className="flex items-center gap-2 truncate">
                    <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                    <span className="truncate font-medium text-text-700">{entry.name}</span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0 tabular text-text-500">
                    <span className="font-semibold text-text-900">{formatNumber(entry.value)}</span>
                    <span className="text-[11px] text-text-400">(%{pct})</span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}
