import React from "react";

export function PageHeader({ title, subtitle, actions, testId = "page-header" }) {
  return (
    <div
      className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-8"
      data-testid={testId}
    >
      <div>
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-900">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-2 text-sm text-slate-500 max-w-2xl">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

export function KpiCard({ label, value, hint, accent, testId }) {
  return (
    <div className="card-flat p-5 rise-in" data-testid={testId}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value mt-2" data-testid={`${testId}-value`}>
        {value}
      </div>
      {hint && <div className="mt-2 text-xs text-slate-500">{hint}</div>}
      {accent && <div className={`mt-3 h-1 w-10 rounded-full ${accent}`} />}
    </div>
  );
}

export function SectionTitle({ children, right }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-[11px] uppercase tracking-[0.18em] font-bold text-slate-500">
        {children}
      </h2>
      {right}
    </div>
  );
}

export const currency = (n) => `$${(n || 0).toLocaleString()}`;
export const nfmt = (n) => (n || 0).toLocaleString();
