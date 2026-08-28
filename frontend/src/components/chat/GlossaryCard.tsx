import type { ChatGlossaryItem } from "@/types/api";

export function GlossaryCard({ items }: { items: ChatGlossaryItem[] }) {
  if (!items.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {items.map((g) => (
        <div
          key={g.term_id}
          className="rounded-lg border border-border bg-surface px-3 py-2.5"
        >
          <p className="text-[11px] text-text-500">Terim</p>
          <p className="mt-0.5 text-sm font-medium text-text-900">{g.term}</p>
          <p className="mt-1.5 text-xs leading-relaxed text-text-500">{g.definition}</p>
          {g.conventional_equivalent && (
            <p className="mt-2 text-[11px] text-text-500">
              Konvansiyonel karşılık:{" "}
              <span className="text-text-700">{g.conventional_equivalent}</span>
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
