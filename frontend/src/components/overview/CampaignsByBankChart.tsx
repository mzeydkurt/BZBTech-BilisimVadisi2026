import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { BankCampaignCount } from "@/types/api";

/** Banka başına kampanya hacmi — yatay bar, banka adları uzun olduğu için. */
export function CampaignsByBankChart({ data }: { data: BankCampaignCount[] }) {
  const chartData = [...data].sort((a, b) => b.count - a.count);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Bankaya Göre Kampanya Hacmi</CardTitle>
      </CardHeader>
      <CardContent>
        <div style={{ width: "100%", height: Math.max(chartData.length * 34, 200) }}>
          <ResponsiveContainer>
            <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke="var(--border)" />
              <XAxis
                type="number"
                allowDecimals={false}
                tick={{ fontSize: 12, fill: "var(--text-500)" }}
              />
              <YAxis
                type="category"
                dataKey="bank_name"
                width={140}
                tick={{ fontSize: 12, fill: "var(--text-500)" }}
              />
              <Tooltip
                formatter={(value: number) => formatNumber(value)}
                contentStyle={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
              <Bar
                dataKey="count"
                fill="var(--brand-500)"
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
