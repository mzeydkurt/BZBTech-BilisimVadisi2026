import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CampaignsPage } from "@/pages/CampaignsPage";
import { ChatPage } from "@/pages/ChatPage";
import { ComparePage } from "@/pages/ComparePage";
import { ExtractPage } from "@/pages/ExtractPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { ProductDetailPage } from "@/pages/ProductDetailPage";
import { ProductsPage } from "@/pages/ProductsPage";
import { SimulatorPage } from "@/pages/SimulatorPage";

// §10.4: retry 1, staleTime 30 sn. Hatalar bileşenlere `isError` ile ulaşır ve
// ErrorState ile gösterilir — boş sonuçla asla karıştırılmaz.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <Router>
          <AppShell>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/campaigns" element={<CampaignsPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:id" element={<ProductDetailPage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/simulator" element={<SimulatorPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/extract" element={<ExtractPage />} />
              <Route
                path="*"
                element={
                  <div className="rounded-lg border border-border bg-surface px-6 py-12 text-center">
                    <p className="font-semibold text-text-900">Sayfa bulunamadı</p>
                    <p className="mt-1 text-sm text-text-500">
                      Aradığınız sayfa mevcut değil.
                    </p>
                  </div>
                }
              />
            </Routes>
          </AppShell>
        </Router>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
