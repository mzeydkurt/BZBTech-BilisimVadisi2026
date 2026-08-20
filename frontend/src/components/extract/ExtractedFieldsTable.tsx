import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatPercent } from "@/lib/format";
import type { ExtractedFieldOut } from "@/types/api";

const METHOD_LABELS: Record<string, string> = {
  table: "Tablo",
  rule: "Kural",
  llm: "Model",
};

export function ExtractedFieldsTable({ fields }: { fields: Record<string, ExtractedFieldOut> }) {
  const entries = Object.entries(fields);

  if (entries.length === 0) {
    return <p className="text-sm text-text-500">Metinden bir alan çıkarılamadı.</p>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead>Alan</TableHead>
            <TableHead>Değer</TableHead>
            <TableHead className="text-right">Güven</TableHead>
            <TableHead className="w-24">Yöntem</TableHead>
            <TableHead>Kanıt</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map(([fieldName, field]) => (
            <TableRow key={fieldName}>
              <TableCell className="font-medium text-text-900">{fieldName}</TableCell>
              <TableCell className="tabular text-text-900">
                {field.value} {field.unit && <span className="text-text-500">{field.unit}</span>}
                {field.validation_note && (
                  <p className="text-xs text-warn-600">{field.validation_note}</p>
                )}
              </TableCell>
              <TableCell className="tabular text-right text-text-500">
                {formatPercent(field.confidence, { scale: "unit", decimals: 0 })}
              </TableCell>
              <TableCell>
                <span className="rounded-sm border border-border px-1.5 py-0.5 text-xs text-text-500">
                  {METHOD_LABELS[field.method] ?? field.method}
                </span>
              </TableCell>
              <TableCell className="text-xs text-text-500">
                {field.evidence ? `“${field.evidence}”` : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
