import {
  LayoutDashboard,
  Table2,
  Landmark,
  HandCoins,
  ArrowLeftRight,
  Calculator,
  MessageSquare,
  FlaskConical,
  Shield,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Genel Bakış", icon: LayoutDashboard, end: true },
  { to: "/campaigns", label: "Kampanyalar", icon: Table2, end: false },
  { to: "/financing", label: "Finansmanlar", icon: Landmark, end: false },
  { to: "/katilim-hesabi", label: "Katılım Hesabı", icon: HandCoins, end: false },
  { to: "/compare", label: "Karşılaştırma", icon: ArrowLeftRight, end: false },
  { to: "/simulator", label: "Simülatör", icon: Calculator, end: false },
  { to: "/chat", label: "Katibim-AI", icon: MessageSquare, end: false },
  { to: "/extract", label: "Çıkarım Lab", icon: FlaskConical, end: false },
];

export function Sidebar() {
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-border bg-brand-900">
      <div className="border-b border-white/10 px-4 py-4">
        <p className="text-sm font-semibold leading-tight text-white">
          KATİP
        </p>
        <p className="text-xs text-white/70">Katılım Bankacılığı Kampanya Analiz Platformu</p>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto p-2" aria-label="Ana gezinme">
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded px-3 py-2 text-sm transition-colors duration-150",
                    isActive
                      ? "bg-white/10 font-medium text-white"
                      : "text-white/70 hover:bg-white/5 hover:text-white",
                  )
                }
              >
                <item.icon className="h-4 w-4" aria-hidden="true" />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-auto border-t border-white/10 p-2">
        <NavLink
          to="/admin"
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2 rounded px-3 py-2 text-sm transition-colors duration-150",
              isActive
                ? "bg-white/10 font-medium text-white"
                : "text-white/70 hover:bg-white/5 hover:text-white",
            )
          }
        >
          <Shield className="h-4 w-4" aria-hidden="true" />
          Admin
        </NavLink>
        <p className="mt-2 px-3 pb-2 text-xs text-white/50">
          Veriler bankaların kamuya açık sayfalarından toplanmıştır.
        </p>
      </div>
    </aside>
  );
}
