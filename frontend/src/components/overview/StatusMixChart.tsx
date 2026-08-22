import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";

interface StatusMixChartProps {
  active: number;
  upcoming: number;
  expired: number;
  unknown: number;
}

const SLICES = [
  { key: "active", label: "Aktif", color: "var(--brand-500)" },
  { key: "upcoming", label: "Yaklaşan", color: "var(--teal-500)" },
  { key: "expired", label: "Süresi dolan", color: "var(--text-500)" },
  { key: "unknown", label: "Tarihsiz", color: "var(--warn-600)" },
] as const;

/** Kampanya durum karışımı — donut. */
export function StatusMixChart({ active, upcoming, expired, unknown }: StatusMixChartProps) {
  const values = { active, upcoming, expired, unknown };
  const chartData = SLICES.map((s) => ({
    name: s.label,
    value: values[s.key],
    color: s.color,
  })).filter((d) => d.value > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Durum Dağılımı</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={55}
                outerRadius={85}
                paddingAngle={1}
                isAnimationActive={false}
              >
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
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
        <ul className="mt-2 grid grid-cols-2 gap-1 text-xs text-text-500">
          {SLICES.map((s) => (
            <li key={s.key} className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: s.color }} />
              {s.label}: {formatNumber(values[s.key])}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
