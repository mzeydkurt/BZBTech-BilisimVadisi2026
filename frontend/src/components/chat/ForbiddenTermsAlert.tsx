import { AlertTriangle } from "lucide-react";

/**
 * ⚠️ Uyum açısından kritik: katılım bankacılığı ilkeleri gereği yasaklı
 * terimler kullanıldığında bu uyarı gizlenmez, her zaman görünür kalır.
 */
export function ForbiddenTermsAlert({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-warn-600/40 bg-surface px-4 py-3 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn-600" aria-hidden="true" />
      <p className="text-text-900">{message}</p>
    </div>
  );
}
