import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { KatilimHesabiRow } from "@/types/api";

const VADE_ETIKETI: Record<string, string> = {
  aylik: "Aylık",
  "3_aylik": "3 Aylık",
  "6_aylik": "6 Aylık",
  yillik: "Yıllık",
};

const KAYNAK_ETIKETI: Record<string, string> = {
  bank_site: "Banka Sitesi",
  tkbb_veripetegi: "TKBB",
};

const PARA_SIRASI = ["TRY", "USD", "EUR"];
const VADE_SIRASI = ["aylik", "3_aylik", "6_aylik", "yillik"];

/** `PARA_SIRASI`'nde olmayan bir para birimi (ör. XAU/altın) SONA gider,
 * `indexOf`'un döndürdüğü -1 başa çekmesin diye. */
function paraSirasi(para: string): number {
  const index = PARA_SIRASI.indexOf(para);
  return index === -1 ? PARA_SIRASI.length : index;
}

/**
 * Görülen tüm hücre anahtarlarını (vade|para_birimi) ÖNCE para birimine
 * (TRY → USD → EUR → diğer), SONRA vadeye göre dizer — TL/USD/EUR blokları
 * birbirine karışmasın diye. Vade-öncelikli sıralama üç para birimini her
 * vadede iç içe geçiriyordu.
 */
function columnsOf(rows: KatilimHesabiRow[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row.values)) seen.add(key);
  }
  return Array.from(seen).sort((a, b) => {
    const [vadeA = "", paraA = ""] = a.split("|");
    const [vadeB = "", paraB = ""] = b.split("|");
    const paraFarki = paraSirasi(paraA) - paraSirasi(paraB);
    if (paraFarki !== 0) return paraFarki;
    return VADE_SIRASI.indexOf(vadeA) - VADE_SIRASI.indexOf(vadeB);
  });
}

/** Sütun bir önceki sütundan farklı bir para birimiyle başlıyorsa görsel ayraç sınıfı. */
function grubuBaslatiyorMu(columns: string[], index: number): boolean {
  if (index === 0) return false;
  const [, oncekiPara = ""] = columns[index - 1]!.split("|");
  const [, buPara = ""] = columns[index]!.split("|");
  return oncekiPara !== buPara;
}

export function KatilimHesabiTable({ rows }: { rows: KatilimHesabiRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-500">Bu filtrelerle eşleşen bir kayıt bulunmuyor.</p>
    );
  }

  const columns = columnsOf(rows);

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead>Banka</TableHead>
            {columns.map((key, index) => {
              const [vade = "", para = ""] = key.split("|");
              return (
                <TableHead
                  key={key}
                  className={cn(
                    "text-right",
                    grubuBaslatiyorMu(columns, index) && "border-l-2 border-border",
                  )}
                >
                  {VADE_ETIKETI[vade] ?? vade}
                  <span className="ml-1 text-text-400">{para}</span>
                </TableHead>
              );
            })}
            <TableHead className="w-24">Kaynak</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.bank_code}>
              <TableCell className="font-medium text-text-900">{row.bank_name}</TableCell>
              {columns.map((key, index) => (
                <TableCell
                  key={key}
                  className={cn(
                    "tabular text-right text-text-900",
                    grubuBaslatiyorMu(columns, index) && "border-l-2 border-border",
                  )}
                >
                  {row.values[key] !== undefined ? formatPercent(row.values[key]) : "—"}
                </TableCell>
              ))}
              <TableCell>
                {row.cross_check ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="cursor-help text-xs text-text-500 underline decoration-dotted">
                        {KAYNAK_ETIKETI[row.data_source] ?? row.data_source}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      Banka sitesi: {formatPercent(row.cross_check.bank_site_value)} · TKBB:{" "}
                      {formatPercent(row.cross_check.tkbb_value)} · eşleşme:{" "}
                      {row.cross_check.match}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <span className="text-xs text-text-500">
                    {KAYNAK_ETIKETI[row.data_source] ?? row.data_source}
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
