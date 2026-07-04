import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, KpiCard, SectionTitle, currency, nfmt } from "../components/ui-bits";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import ChartFrame from "../components/ChartFrame";
import {
  Users2,
  DollarSign,
  Activity,
  Calendar,
  TrendingUp,
  Megaphone,
  ArrowRight,
  Info,
  CheckCircle2,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

export default function Dashboard() {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [events, setEvents] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      const [d, e] = await Promise.all([
        api.get("/dashboard/global"),
        api.get("/events"),
      ]);
      setData(d.data);
      setEvents(e.data);
    })();
  }, []);

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="dashboard-page">
      <PageHeader
        title={t("globalOverview")}
        subtitle={t("tagline")}
        actions={
          <button
            onClick={() => navigate("/events")}
            className="btn btn-outline"
            data-testid="dashboard-view-events-btn"
          >
            {t("events")}
            <ArrowRight className="w-4 h-4" />
          </button>
        }
      />

      {data?.metrics_status === "no_verified_metrics" ? (
        <div
          className="mb-6 card-flat p-4 flex items-start gap-3 border-orange-200 bg-orange-50/60"
          data-testid="dashboard-metrics-banner"
        >
          <Info className="w-4 h-4 mt-0.5 text-orange-600 shrink-0" />
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Verified metrics pending
            </div>
            <div className="text-xs text-slate-600 mt-0.5">
              {data.metrics_message ||
                "Add manual KPI data or import a CSV to populate performance metrics."}
            </div>
          </div>
        </div>
      ) : data?.metrics_status === "verified" ? (
        <div
          className="mb-6 card-flat p-4 flex items-start gap-3 border-green-200 bg-green-50/60"
          data-testid="dashboard-metrics-verified"
        >
          <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-600 shrink-0" />
          <div>
            <div className="text-sm font-semibold text-slate-900">
              Verified KPI data
            </div>
            <div className="text-xs text-slate-600 mt-0.5">
              Aggregated from {data.records_count} verified KPI record{data.records_count === 1 ? "" : "s"} across all events.
            </div>
          </div>
        </div>
      ) : null}

      {/* KPI bento row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6 mb-8">
        <KpiCard
          label={t("totalLeads")}
          value={nfmt(data?.total_leads)}
          hint={`${nfmt(data?.leads_form_filled)} ${t("formsFilled").toLowerCase()}`}
          accent="bg-blue-500"
          testId="kpi-total-leads"
        />
        <KpiCard
          label={t("engagement")}
          value={nfmt(data?.engagement)}
          hint={`${nfmt(data?.reach)} ${t("reach").toLowerCase()}`}
          accent="bg-orange-500"
          testId="kpi-engagement"
        />
        <KpiCard
          label={t("meetingsBooked")}
          value={nfmt(data?.leads_booked)}
          hint={`${nfmt(data?.leads_purchased)} ${t("purchases").toLowerCase()}`}
          accent="bg-green-500"
          testId="kpi-meetings"
        />
        <KpiCard
          label={t("budgetPlanned")}
          value={currency(data?.budget_planned)}
          hint={`${currency(data?.budget_actual)} spent`}
          accent="bg-slate-900"
          testId="kpi-budget"
        />
      </div>

      {/* Trend + Events */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 card-flat p-5 rise-in" data-testid="trend-chart">
          <SectionTitle>{t("performanceTrend")}</SectionTitle>
          <ChartFrame className="h-72">
            <AreaChart data={data?.trend || []}>
              <defs>
                <linearGradient id="rr" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2563EB" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#2563EB" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="ee" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#F97316" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#F97316" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#E2E8F0" vertical={false} />
              <XAxis dataKey="date" tickFormatter={(d) => d?.slice(5)} />
              <YAxis />
              <Tooltip
                contentStyle={{
                  background: "white",
                  border: "1px solid #E2E8F0",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Area
                type="monotone"
                dataKey="reach"
                stroke="#2563EB"
                strokeWidth={2}
                fill="url(#rr)"
                name={t("reach")}
              />
              <Area
                type="monotone"
                dataKey="engagement"
                stroke="#F97316"
                strokeWidth={2}
                fill="url(#ee)"
                name={t("engagement")}
              />
            </AreaChart>
          </ChartFrame>
        </div>

        <div className="lg:col-span-4 space-y-4">
          <div className="card-flat p-5 rise-in-2">
            <SectionTitle>{t("perEventDashboard")}</SectionTitle>
            {events.length === 0 && (
              <div className="text-sm text-slate-500 py-6 text-center">
                {t("noData")}
              </div>
            )}
            <div className="space-y-2">
              {events.slice(0, 5).map((ev) => (
                <button
                  key={ev.id}
                  onClick={() => navigate(`/events/${ev.id}`)}
                  className="w-full text-start p-3 rounded-lg border border-slate-100 hover:border-slate-300 transition-colors flex items-center gap-3"
                  data-testid={`event-quick-${ev.id}`}
                >
                  <Calendar className="w-4 h-4 text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-slate-900 truncate">
                      {ev.name}
                    </div>
                    <div className="text-[11px] text-slate-500 mono">
                      {ev.start_date}
                    </div>
                  </div>
                  <span className="badge-pill badge-slate">{ev.status}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="card-flat p-5 rise-in-3">
            <SectionTitle>{t("posts")}</SectionTitle>
            <div className="flex items-baseline gap-2">
              <div className="kpi-value">{nfmt(data?.posts_count)}</div>
              <div className="text-xs text-slate-500">
                across {nfmt(data?.campaigns_count)} {t("campaignsCount").toLowerCase()}
              </div>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              <div className="p-2 rounded-md bg-slate-50">
                <div className="text-xs text-slate-500">{t("clicks")}</div>
                <div className="font-bold text-slate-900">{nfmt(data?.clicks)}</div>
              </div>
              <div className="p-2 rounded-md bg-slate-50">
                <div className="text-xs text-slate-500">{t("impressions")}</div>
                <div className="font-bold text-slate-900">{nfmt(data?.impressions)}</div>
              </div>
              <div className="p-2 rounded-md bg-slate-50">
                <div className="text-xs text-slate-500">{t("noShows")}</div>
                <div className="font-bold text-slate-900">{nfmt(data?.leads_no_show)}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
