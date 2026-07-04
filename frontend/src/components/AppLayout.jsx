import React from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Calendar,
  Megaphone,
  Sparkles,
  Users,
  Settings,
  Plug,
  LogOut,
  Languages,
} from "lucide-react";
import { useI18n } from "../lib/i18n";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/", key: "dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/events", key: "events", icon: Calendar, testid: "nav-events" },
  { to: "/ai", key: "aiBuilder", icon: Sparkles, testid: "nav-ai" },
  { to: "/integrations", key: "integrations", icon: Plug, testid: "nav-integrations" },
  { to: "/users", key: "users", icon: Users, testid: "nav-users", adminOnly: true },
  { to: "/settings", key: "settings", icon: Settings, testid: "nav-settings", adminOnly: true },
];

export default function AppLayout() {
  const { t, toggle, lang } = useI18n();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen surface flex" data-testid="app-shell">
      {/* Sidebar */}
      <aside
        className="w-64 shrink-0 bg-white border-e border-slate-200 flex flex-col"
        data-testid="sidebar"
      >
        <div className="px-5 py-6 border-b border-slate-100">
          <div
            onClick={() => navigate("/")}
            className="flex items-center gap-2 cursor-pointer select-none"
            data-testid="brand-logo"
          >
            <div className="w-9 h-9 rounded-lg bg-slate-900 text-white grid place-items-center relative overflow-hidden">
              <Sparkles className="w-4 h-4 text-orange-400" />
            </div>
            <div>
              <div className="text-[15px] font-bold tracking-tight text-slate-900">
                {t("appName")}
              </div>
              <div className="text-[11px] tracking-wide uppercase text-slate-500">
                {t("tagline")}
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.filter((n) => !n.adminOnly || user?.role === "admin").map((n) => {
            const Icon = n.icon;
            return (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                data-testid={n.testid}
                className={({ isActive }) => `link-nav ${isActive ? "active" : ""}`}
              >
                <Icon className="w-4 h-4" strokeWidth={2} />
                <span>{t(n.key)}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="px-3 pt-3 pb-4 border-t border-slate-100">
          <button
            onClick={toggle}
            data-testid="language-toggle-btn"
            className="link-nav w-full"
          >
            <Languages className="w-4 h-4" />
            <span className="mono text-[13px]">{t("language")}</span>
          </button>
          <div className="mx-2 mt-3 mb-2 text-[11px] text-slate-500 uppercase tracking-widest">
            {t("signedInAs")}
          </div>
          <div className="mx-2 flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-orange-500/90 text-white grid place-items-center font-bold text-xs">
              {user?.name?.[0] || "A"}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-900 truncate">
                {user?.name}
              </div>
              <div className="text-xs text-slate-500 truncate">{user?.email}</div>
            </div>
            <button
              onClick={logout}
              className="btn btn-ghost !p-2"
              data-testid="logout-btn"
              title={t("logout")}
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
