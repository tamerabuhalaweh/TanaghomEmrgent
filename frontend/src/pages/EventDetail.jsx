import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { PageHeader, KpiCard, SectionTitle, currency, nfmt } from "../components/ui-bits";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import Modal from "../components/Modal";
import EventKpiPanel from "../components/EventKpiPanel";
import {
  Plus, Megaphone, Trash2, Sparkles, ArrowLeft, Calendar as CalIcon, MapPin, Info, CheckCircle2,
} from "lucide-react";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { toast } from "sonner";

const PLATFORMS = ["meta", "instagram", "youtube", "tiktok", "whatsapp", "email"];
const CAMPAIGN_EMPTY = (event_id) => ({
  event_id,
  name: "",
  goal: "max_reach",
  start_date: "",
  end_date: "",
  budget_planned: 0,
  platforms: ["meta", "instagram"],
  audience: { age_range: "25-40", gender: "all", geo: "", segment: "warm+cold" },
});

const LEAD_EMPTY = (event_id) => ({
  event_id, name: "", email: "", phone: "", source: "form",
  stage: "form_filled", tag: "", notes: "",
});

const COLORS = ["#2563EB", "#F97316", "#16A34A", "#7C3AED", "#DC2626", "#0EA5E9"];

export default function EventDetail() {
  const { t, lang } = useI18n();
  const { id } = useParams();
  const navigate = useNavigate();
  const [dash, setDash] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [leads, setLeads] = useState([]);
  const [openC, setOpenC] = useState(false);
  const [openL, setOpenL] = useState(false);
  const [cForm, setCForm] = useState(CAMPAIGN_EMPTY(id));
  const [lForm, setLForm] = useState(LEAD_EMPTY(id));

  const load = useCallback(async () => {
    const [d, c, l] = await Promise.all([
      api.get(`/dashboard/event/${id}`),
      api.get(`/events/${id}/campaigns`),
      api.get(`/events/${id}/leads`),
    ]);
    setDash(d.data);
    setCampaigns(c.data);
    setLeads(l.data);
  }, [id]);

  useEffect(() => {
    load();
    setCForm(CAMPAIGN_EMPTY(id));
    setLForm(LEAD_EMPTY(id));
  }, [id, load]);

  const ev = dash?.event;

  const saveCampaign = async (e) => {
    e.preventDefault();
    try {
      await api.post("/campaigns", {
        ...cForm,
        budget_planned: Number(cForm.budget_planned) || 0,
      });
      toast.success(t("createdSuccess"));
      setOpenC(false);
      setCForm(CAMPAIGN_EMPTY(id));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const saveLead = async (e) => {
    e.preventDefault();
    try {
      await api.post("/leads", lForm);
      toast.success(t("createdSuccess"));
      setOpenL(false);
      setLForm(LEAD_EMPTY(id));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const delCampaign = async (cid) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    await api.delete(`/campaigns/${cid}`);
    load();
  };

  const budgetData = [
    { label: t("budgetPlanned"), value: dash?.budget_planned || 0 },
    { label: "Actual", value: dash?.budget_actual || 0 },
  ];

  const platformData = (dash?.platform_breakdown || []).map((p) => ({
    ...p,
    name: p.platform,
    value: p.reach,
  }));

  const funnelStages = [
    { key: "leads_new", label: t("totalLeads") },
    { key: "leads_form_filled", label: t("formsFilled") },
    { key: "leads_booked", label: t("meetingsBooked") },
    { key: "leads_purchased", label: t("purchases") },
    { key: "leads_no_show", label: t("noShows") },
  ];

  return (
    <div className="pb-12" data-testid="event-detail-page">
      {/* Hero */}
      <div className="relative h-64 md:h-72 overflow-hidden grain">
        <img
          src={ev?.cover_image || "https://images.unsplash.com/photo-1762968274962-20c12e6e8ecd?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHwxfHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85"}
          alt={ev?.name}
          className="w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/85 via-slate-900/50 to-slate-900/10" />
        <div className="absolute inset-x-0 top-0 p-6 md:px-10">
          <button
            onClick={() => navigate("/events")}
            className="btn btn-outline !bg-white/10 !text-white !border-white/30 hover:!bg-white/20"
            data-testid="event-back-btn"
          >
            <ArrowLeft className="w-4 h-4" />
            {t("events")}
          </button>
        </div>
        <div className="absolute inset-x-0 bottom-0 p-6 md:px-10 md:pb-8 text-white">
          <div className="text-[11px] uppercase tracking-[0.2em] text-orange-300 font-bold mb-2">
            {t("dashboardOf")} {ev?.type?.replaceAll("_", " ")}
          </div>
          <h1 className="text-3xl md:text-4xl font-black tracking-tight">
            {ev?.name}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-white/85">
            {ev?.start_date && (
              <div className="flex items-center gap-1.5">
                <CalIcon className="w-4 h-4" />
                <span className="mono">
                  {ev.start_date}
                  {ev.end_date ? ` → ${ev.end_date}` : ""}
                </span>
              </div>
            )}
            {ev?.location && (
              <div className="flex items-center gap-1.5">
                <MapPin className="w-4 h-4" />
                <span>{ev.location}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="p-6 md:p-10 max-w-[1400px] mx-auto">
        {dash?.metrics_status === "no_verified_metrics" ? (
          <div
            className="mb-6 card-flat p-4 flex items-start gap-3 border-orange-200 bg-orange-50/60"
            data-testid="event-metrics-banner"
          >
            <Info className="w-4 h-4 mt-0.5 text-orange-600 shrink-0" />
            <div>
              <div className="text-sm font-semibold text-slate-900">
                Verified metrics pending
              </div>
              <div className="text-xs text-slate-600 mt-0.5">
                {dash.metrics_message ||
                  "Add manual KPI data or import a CSV to populate performance."}
              </div>
            </div>
          </div>
        ) : dash?.metrics_status === "verified" ? (
          <div
            className="mb-6 card-flat p-4 flex items-start gap-3 border-green-200 bg-green-50/60"
            data-testid="event-metrics-verified"
          >
            <CheckCircle2 className="w-4 h-4 mt-0.5 text-green-600 shrink-0" />
            <div>
              <div className="text-sm font-semibold text-slate-900">
                Verified KPI data
              </div>
              <div className="text-xs text-slate-600 mt-0.5">
                Metrics are aggregated from {dash.records_count} verified KPI record{dash.records_count === 1 ? "" : "s"}.
              </div>
            </div>
          </div>
        ) : null}

        {/* Funnel KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 md:gap-4 mb-8 -mt-16 relative z-10">
          {funnelStages.map((s, i) => (
            <KpiCard
              key={s.key}
              label={s.label}
              value={nfmt(dash?.[s.key])}
              accent={
                ["bg-blue-500", "bg-orange-500", "bg-purple-500", "bg-green-500", "bg-red-500"][i]
              }
              testId={`kpi-funnel-${s.key}`}
            />
          ))}
        </div>

        {/* Second row KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <KpiCard
            label={t("revenue")}
            value={currency(dash?.revenue)}
            testId="kpi-revenue"
          />
          <KpiCard
            label={t("roi")}
            value={`${(dash?.roi_percent || 0).toFixed(0)}%`}
            testId="kpi-roi"
          />
          <KpiCard
            label={t("reach")}
            value={nfmt(dash?.reach)}
            hint={`${nfmt(dash?.engagement)} ${t("engagement").toLowerCase()}`}
            testId="kpi-event-reach"
          />
          <KpiCard
            label={t("campaignsCount")}
            value={nfmt(dash?.campaigns_count)}
            hint={`${nfmt(dash?.posts_count)} ${t("posts").toLowerCase()}`}
            testId="kpi-event-campaigns"
          />
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8">
          <div className="lg:col-span-7 card-flat p-5">
            <SectionTitle>{t("plannedVsActual")}</SectionTitle>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={budgetData}>
                  <CartesianGrid stroke="#E2E8F0" vertical={false} />
                  <XAxis dataKey="label" />
                  <YAxis />
                  <Tooltip
                    contentStyle={{ background: "white", border: "1px solid #E2E8F0", borderRadius: 8, fontSize: 12 }}
                  />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    <Cell fill="#0F172A" />
                    <Cell fill="#F97316" />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="lg:col-span-5 card-flat p-5">
            <SectionTitle>{t("platformBreakdown")}</SectionTitle>
            {platformData.length === 0 ? (
              <div className="h-64 grid place-items-center text-sm text-slate-500">
                {t("noData")}
              </div>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={platformData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={50}
                      outerRadius={90}
                      paddingAngle={2}
                    >
                      {platformData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "white", border: "1px solid #E2E8F0", borderRadius: 8, fontSize: 12 }}
                    />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Verified KPI records + CSV import */}
        <EventKpiPanel eventId={id} onChanged={load} />

        {/* Campaigns */}
        <div className="card-flat p-5 mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold tracking-tight text-slate-900">
              {t("campaigns")}
            </h2>
            <div className="flex items-center gap-2">
              <Link
                to={`/ai?event=${id}`}
                className="btn btn-ai"
                data-testid="event-ai-builder-link"
              >
                <Sparkles className="w-4 h-4" />
                {t("aiBuilder")}
              </Link>
              <button
                onClick={() => setOpenC(true)}
                className="btn btn-primary"
                data-testid="event-new-campaign-btn"
              >
                <Plus className="w-4 h-4" />
                {t("newCampaign")}
              </button>
            </div>
          </div>
          {campaigns.length === 0 ? (
            <div className="text-sm text-slate-500 py-6 text-center">
              {t("noData")}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {campaigns.map((c) => (
                <div
                  key={c.id}
                  className="border border-slate-200 rounded-lg p-4 hover:border-slate-400 transition-colors"
                  data-testid={`campaign-card-${c.id}`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-orange-600 font-bold">
                        {c.goal.replaceAll("_", " ")}
                      </div>
                      <div className="text-base font-bold text-slate-900 mt-1">
                        {c.name}
                      </div>
                    </div>
                    <button
                      onClick={() => delCampaign(c.id)}
                      className="btn btn-danger !p-1.5"
                      data-testid={`campaign-delete-${c.id}`}
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="mt-2 text-xs text-slate-500 mono">
                    {c.start_date} → {c.end_date}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {c.platforms.map((p) => (
                      <span key={p} className="badge-pill badge-blue">{p}</span>
                    ))}
                  </div>
                  <div className="mt-3 flex items-center justify-between text-xs">
                    <div className="text-slate-500">{t("budgetPlanned")}</div>
                    <div className="font-bold text-slate-900">{currency(c.budget_planned)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Leads */}
        <div className="card-flat p-5">
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div>
              <h2 className="text-lg font-bold tracking-tight text-slate-900">Leads</h2>
              {dash?.ghl_status && (
                <p className="text-xs text-slate-500 mt-1" data-testid="event-ghl-status-line">
                  {dash.ghl_status.credential_status === "missing"
                    ? "GoHighLevel not configured. Leads can still be managed locally, but CRM sync is off."
                    : `GHL: ${dash.ghl_status.credential_status} · Mappings: ${dash.ghl_status.mapping_status} · Read sync: ${dash.ghl_status.read_sync_enabled ? "on" : "off"}`}
                </p>
              )}
              {dash?.leads_by_source && (
                <div className="flex flex-wrap gap-1 mt-2" data-testid="event-leads-by-source">
                  <span className="badge-pill badge-orange">GHL CRM · {dash.leads_by_source.gohighlevel || 0}</span>
                  <span className="badge-pill badge-slate">Local · {dash.leads_by_source.local || 0}</span>
                  {["cold", "warm", "hot", "buyer"].map((k) => (
                    <span key={k} className="badge-pill badge-blue">
                      {k} · {(dash.leads_by_temperature || {})[k] || 0}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => setOpenL(true)}
              className="btn btn-outline"
              data-testid="event-new-lead-btn"
            >
              <Plus className="w-4 h-4" />
              Add Lead
            </button>
          </div>
          {leads.length === 0 ? (
            <div className="text-sm text-slate-500 py-6 text-center">
              {t("noData")}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-[10px] uppercase tracking-widest text-slate-500">
                  <tr className="border-b border-slate-100">
                    <th className="text-start py-2">{t("name")}</th>
                    <th className="text-start py-2">{t("email")}</th>
                    <th className="text-start py-2">CRM source</th>
                    <th className="text-start py-2">Temperature</th>
                    <th className="text-start py-2">Stage</th>
                    <th className="text-start py-2">Last synced</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((l) => (
                    <tr key={l.id} className="border-b border-slate-50" data-testid={`lead-row-${l.id}`}>
                      <td className="py-2 font-medium text-slate-900">{l.name}</td>
                      <td className="py-2 mono text-xs text-slate-600">{l.email}</td>
                      <td className="py-2">
                        <span className={`badge-pill ${
                          l.source_of_truth === "gohighlevel" ? "badge-orange" : "badge-slate"
                        }`}>
                          {l.source_of_truth === "gohighlevel" ? "GHL CRM" : "Local"}
                        </span>
                      </td>
                      <td className="py-2">
                        {l.lead_temperature ? (
                          <span className={`badge-pill ${
                            l.lead_temperature === "buyer" ? "badge-green"
                            : l.lead_temperature === "hot" ? "badge-red"
                            : l.lead_temperature === "warm" ? "badge-orange"
                            : "badge-blue"
                          }`}>
                            {l.lead_temperature}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-2">
                        <span className={`badge-pill ${
                          l.stage === "purchased" ? "badge-green"
                          : l.stage === "booked" ? "badge-blue"
                          : l.stage === "no_show" ? "badge-red"
                          : "badge-orange"
                        }`}>
                          {l.stage}
                        </span>
                      </td>
                      <td className="py-2 mono text-[11px] text-slate-500">
                        {l.external_last_synced_at
                          ? new Date(l.external_last_synced_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Campaign modal */}
      <Modal open={openC} onClose={() => setOpenC(false)} title={t("newCampaign")} testId="campaign-modal">
        <form onSubmit={saveCampaign} className="space-y-3">
          <div>
            <label className="field-label">{t("campaignName")}</label>
            <input required className="field-input" value={cForm.name}
              onChange={(e) => setCForm({ ...cForm, name: e.target.value })}
              data-testid="campaign-form-name" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("goal")}</label>
              <select className="field-input" value={cForm.goal}
                onChange={(e) => setCForm({ ...cForm, goal: e.target.value })}
                data-testid="campaign-form-goal">
                <option value="max_reach">{t("goalReach")}</option>
                <option value="conversion">{t("goalConversion")}</option>
                <option value="engagement">{t("goalEngagement")}</option>
              </select>
            </div>
            <div>
              <label className="field-label">{t("budgetPlanned")} ($)</label>
              <input type="number" min="0" className="field-input" value={cForm.budget_planned}
                onChange={(e) => setCForm({ ...cForm, budget_planned: e.target.value })}
                data-testid="campaign-form-budget" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("startDate")}</label>
              <input required type="date" className="field-input" value={cForm.start_date}
                onChange={(e) => setCForm({ ...cForm, start_date: e.target.value })} />
            </div>
            <div>
              <label className="field-label">{t("endDate")}</label>
              <input required type="date" className="field-input" value={cForm.end_date}
                onChange={(e) => setCForm({ ...cForm, end_date: e.target.value })} />
            </div>
          </div>
          <div>
            <label className="field-label">{t("platforms")}</label>
            <div className="flex flex-wrap gap-2">
              {PLATFORMS.map((p) => {
                const on = cForm.platforms.includes(p);
                return (
                  <button
                    type="button" key={p}
                    onClick={() => setCForm({ ...cForm, platforms: on ? cForm.platforms.filter(x => x !== p) : [...cForm.platforms, p] })}
                    className={`btn ${on ? "btn-primary" : "btn-outline"} !py-1.5 !px-3 text-xs`}
                    data-testid={`campaign-form-platform-${p}`}
                  >
                    {p}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("ageRange")}</label>
              <input className="field-input" value={cForm.audience.age_range}
                onChange={(e) => setCForm({ ...cForm, audience: { ...cForm.audience, age_range: e.target.value } })} />
            </div>
            <div>
              <label className="field-label">{t("gender")}</label>
              <select className="field-input" value={cForm.audience.gender}
                onChange={(e) => setCForm({ ...cForm, audience: { ...cForm.audience, gender: e.target.value } })}>
                <option value="all">All</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpenC(false)}>{t("cancel")}</button>
            <button type="submit" className="btn btn-primary" data-testid="campaign-form-save">{t("save")}</button>
          </div>
        </form>
      </Modal>

      {/* Lead modal */}
      <Modal open={openL} onClose={() => setOpenL(false)} title="Add Lead" testId="lead-modal">
        <form onSubmit={saveLead} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("name")}</label>
              <input required className="field-input" value={lForm.name}
                onChange={(e) => setLForm({ ...lForm, name: e.target.value })}
                data-testid="lead-form-name" />
            </div>
            <div>
              <label className="field-label">{t("email")}</label>
              <input type="email" className="field-input" value={lForm.email}
                onChange={(e) => setLForm({ ...lForm, email: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">Stage</label>
              <select className="field-input" value={lForm.stage}
                onChange={(e) => setLForm({ ...lForm, stage: e.target.value })}
                data-testid="lead-form-stage">
                <option value="new">new</option>
                <option value="form_filled">form_filled</option>
                <option value="booked">booked</option>
                <option value="purchased">purchased</option>
                <option value="no_show">no_show</option>
              </select>
            </div>
            <div>
              <label className="field-label">Source</label>
              <select className="field-input" value={lForm.source}
                onChange={(e) => setLForm({ ...lForm, source: e.target.value })}>
                <option value="form">form</option>
                <option value="ad">ad</option>
                <option value="referral">referral</option>
                <option value="manual">manual</option>
              </select>
            </div>
          </div>
          <div>
            <label className="field-label">Tag</label>
            <input className="field-input" value={lForm.tag}
              onChange={(e) => setLForm({ ...lForm, tag: e.target.value })} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpenL(false)}>{t("cancel")}</button>
            <button type="submit" className="btn btn-primary" data-testid="lead-form-save">{t("save")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
