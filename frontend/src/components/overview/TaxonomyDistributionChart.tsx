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

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={80}
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
      </CardContent>
    </Card>
  );
}
