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
  const total = active + upcoming + expired + unknown;
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
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                innerRadius={65}
                outerRadius={105}
                paddingAngle={2}
                isAnimationActive={false}
              >
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
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
        <ul className="mt-3 grid grid-cols-2 gap-2 text-xs">
          {SLICES.map((s) => {
            const val = values[s.key];
            const pct = total > 0 ? ((val / total) * 100).toFixed(1) : "0";
            return (
              <li
                key={s.key}
                className="flex items-center justify-between rounded bg-neutral-50 px-2.5 py-1.5 border border-border/50"
              >
                <div className="flex items-center gap-2">
                  <span className="inline-block h-2.5 w-2.5 rounded-full shrink-0" style={{ background: s.color }} />
                  <span className="font-medium text-text-700">{s.label}</span>
                </div>
                <div className="flex items-center gap-1 tabular">
                  <span className="font-semibold text-text-900">{formatNumber(val)}</span>
                  <span className="text-[11px] text-text-400">(%{pct})</span>
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
