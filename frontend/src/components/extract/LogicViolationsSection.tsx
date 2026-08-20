export function LogicViolationsSection({ violations }: { violations: Record<string, string> }) {
  const entries = Object.entries(violations);
  if (entries.length === 0) return null;

  return (
    <section className="rounded-lg border border-warn-600/40 bg-surface p-4">
      <h3 className="text-sm font-semibold text-warn-600">Mantık Tutarsızlıkları</h3>
      <ul className="mt-2 space-y-1">
        {entries.map(([key, message]) => (
          <li key={key} className="text-sm text-text-900">
            <span className="font-medium">{key}:</span> {message}
          </li>
        ))}
      </ul>
    </section>
  );
}
