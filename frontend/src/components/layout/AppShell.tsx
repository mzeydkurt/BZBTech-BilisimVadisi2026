import type { ReactNode } from "react";

import { Sidebar } from "@/components/layout/Sidebar";

/** Uygulama kabuğu: sabit kenar çubuğu + kaydırılabilir içerik alanı. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-neutral-50">
      <Sidebar />
      <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-6">
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
