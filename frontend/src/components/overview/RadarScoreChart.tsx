import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { RadarScore } from "@/types/api";

const AXES = [
  { key: "rate_competitiveness", label: "Oran Rekabetçiliği" },
  { key: "reward_generosity", label: "Ödül Cömertliği" },
  { key: "term_flexibility", label: "Vade Esnekliği" },
  { key: "transparency_index", label: "Şeffaflık" },
] as const;

const SERIES_COLORS = ["var(--brand-700)", "var(--teal-500)", "var(--brand-500)", "#8fb9a8", "#0f3d2e"];

const MIN_MEASURED_AXES = 3;

/**
 * Rekabet radarı.
 *
 * ⚠️ recharts'ın `<Radar>` bileşeninde `<Line>`'daki gibi bir `connectNulls`
 * eşdeğeri yok — `null` eksen değeri sessizce 0 sayılır ve o banka "kötü"
 * görünür. Bunu önlemek için `measured_axes < 3` olan bankalar radara hiç
 * konmaz, ayrı "yetersiz veri" kartı olarak gösterilir. `campaign_volume`
 * kasıtlı olarak eksen listesinde YOK: 0-100 göreli puanlarla aynı radara
 * konacak bir ölçüm değil, o bilgi zaten banka hacmi bar grafiğinde var.
 */
export function RadarScoreChart({ scores }: { scores: RadarScore[] }) {
  const eligible = scores.filter((s) => s.measured_axes >= MIN_MEASURED_AXES);
  const insufficient = scores.filter((s) => s.measured_axes < MIN_MEASURED_AXES);

  const chartData = AXES.map(({ key, label }) => {
    const row: Record<string, string | number> = { axis: label };
    for (const bank of eligible) {
      // Eleme sonrası kalan bankalarda tekil eksen null'u nadir ama yine de
      // mümkün; radar geometrisi her eksende sayısal köşe ister, bu yüzden
      // yalnızca BURADA, son çare olarak 0'a düşürülür.
      row[bank.bank_code] = bank[key] ?? 0;
    }
    return row;
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rekabet Radarı</CardTitle>
        <p className="mt-1 text-xs text-text-500">
          Puanlar bankalar arasında görelidir; 100 = bu eksende en iyi.
        </p>
      </CardHeader>
      <CardContent>
        <div style={{ width: "100%", height: 320 }}>
          <ResponsiveContainer>
            <RadarChart data={chartData} outerRadius="70%">
              <PolarGrid stroke="var(--border)" />
              <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11, fill: "var(--text-500)" }} />
              <PolarRadiusAxis
                domain={[0, 100]}
                tick={{ fontSize: 10, fill: "var(--text-500)" }}
              />
              {eligible.map((bank, index) => (
                <Radar
                  key={bank.bank_code}
                  name={bank.bank_name}
                  dataKey={bank.bank_code}
                  stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                  fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                  fillOpacity={0.12}
                  isAnimationActive={false}
                />
              ))}
              <Tooltip
                formatter={(value: number) => formatNumber(value)}
                contentStyle={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        {insufficient.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-500">
              Yetersiz Veri
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {insufficient.map((bank) => (
                <span
                  key={bank.bank_code}
                  className="rounded border border-dashed border-border px-2 py-1 text-xs text-text-500"
                  title="Radara dahil edilmedi: en az 3 eksende ölçüm gerekir."
                >
                  {bank.bank_name} — {bank.measured_axes}/5 eksen
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
