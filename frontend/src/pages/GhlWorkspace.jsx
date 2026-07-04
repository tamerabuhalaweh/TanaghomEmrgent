import React, { useEffect, useState } from "react";
import { PageHeader, SectionTitle } from "../components/ui-bits";
import GhlIntegrationCard from "../components/GhlIntegrationCard";
import { api } from "../lib/api";
import { RefreshCw, UsersRound } from "lucide-react";
import { toast } from "sonner";

function tempBadge(temp) {
  if (temp === "buyer") return "badge-green";
  if (temp === "hot") return "badge-red";
  if (temp === "warm") return "badge-orange";
  return "badge-blue";
}

export default function GhlWorkspace() {
  const [events, setEvents] = useState([]);
  const [eventId, setEventId] = useState("");
  const [leads, setLeads] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [eventRes, statusRes] = await Promise.all([
        api.get("/events"),
        api.get("/ghl/status"),
      ]);
      const nextEvents = eventRes.data || [];
      setEvents(nextEvents);
      const selectedEvent = eventId || nextEvents[0]?.id || "";
      if (!eventId && selectedEvent) setEventId(selectedEvent);
      setStatus(statusRes.data);
      if (selectedEvent) {
        const leadRes = await api.get(`/events/${selectedEvent}/leads`);
        setLeads(leadRes.data || []);
      } else {
        setLeads([]);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not load GHL workspace");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (eventId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId]);

  const ghlLeads = leads.filter((lead) => lead.source_of_truth === "gohighlevel");
  const localLeads = leads.filter((lead) => lead.source_of_truth !== "gohighlevel");

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="ghl-workspace-page">
      <PageHeader
        title="GoHighLevel"
        subtitle="Keep GHL as the CRM source of truth while Tanaghum becomes the place your team plans, reviews, reports, and acts on lead movement."
        actions={<button onClick={load} className="btn btn-outline"><RefreshCw className="w-4 h-4" /> Refresh</button>}
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <div className="lg:col-span-8">
          <GhlIntegrationCard />
        </div>
        <div className="lg:col-span-4 card-flat p-5">
          <SectionTitle>CRM Operating Model</SectionTitle>
          <div className="w-11 h-11 rounded-lg bg-slate-900 text-white grid place-items-center mb-4">
            <UsersRound className="w-5 h-5 text-orange-400" />
          </div>
          <div className="space-y-3 text-sm">
            <Fact label="Lead source of truth" value={status?.source_of_truth || "gohighlevel"} />
            <Fact label="Tanaghum role" value={status?.local_role || "operating reporting layer"} />
            <Fact label="Read sync" value={status?.read_sync_enabled ? "enabled" : "blocked"} />
            <Fact label="Write back" value={status?.write_back_enabled ? "enabled" : "preview only"} />
          </div>
          {status?.required_actions?.length > 0 && (
            <div className="mt-5 p-3 rounded-md bg-orange-50 border border-orange-200">
              <div className="font-bold text-orange-900 text-sm">Before live sync</div>
              <ul className="mt-1 text-xs text-orange-900 list-disc list-inside space-y-1">
                {status.required_actions.map((item, idx) => <li key={idx}>{item}</li>)}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="card-flat overflow-hidden" data-testid="ghl-leads-panel">
        <div className="px-5 py-4 border-b border-slate-100 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <div className="font-bold text-slate-900">Leads visible in Tanaghum</div>
            <div className="text-xs text-slate-500">GHL leads appear here after pull sync. Local leads remain separate and honest.</div>
          </div>
          <div className="flex items-center gap-2">
            <select className="field-input min-w-[240px]" value={eventId} onChange={(e) => setEventId(e.target.value)}>
              {events.map((event) => <option key={event.id} value={event.id}>{event.name}</option>)}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-5 border-b border-slate-100">
          <Metric label="Total leads" value={leads.length} />
          <Metric label="From GHL" value={ghlLeads.length} tone="orange" />
          <Metric label="Local" value={localLeads.length} tone="slate" />
          <Metric label="Buyers" value={leads.filter((lead) => lead.lead_temperature === "buyer" || lead.stage === "purchased").length} tone="green" />
        </div>
        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading leads...</div>
        ) : leads.length === 0 ? (
          <div className="p-10 text-center">
            <div className="font-bold text-slate-900">No leads loaded for this event</div>
            <p className="text-sm text-slate-500 mt-1">Connect GHL, add tag/stage mappings, and run a pull preview or sync.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-widest text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="text-start p-4">Lead</th>
                  <th className="text-start p-4">CRM Source</th>
                  <th className="text-start p-4">Stage</th>
                  <th className="text-start p-4">Temperature</th>
                  <th className="text-start p-4">Last synced</th>
                </tr>
              </thead>
              <tbody>
                {leads.map((lead) => (
                  <tr key={lead.id} className="border-b border-slate-50" data-testid={`ghl-lead-${lead.id}`}>
                    <td className="p-4">
                      <div className="font-bold text-slate-900">{lead.name}</div>
                      <div className="text-xs text-slate-500">{lead.email || lead.phone || "No contact detail"}</div>
                    </td>
                    <td className="p-4">
                      <span className={`badge-pill ${lead.source_of_truth === "gohighlevel" ? "badge-orange" : "badge-slate"}`}>
                        {lead.source_of_truth === "gohighlevel" ? "GHL CRM" : "Local"}
                      </span>
                    </td>
                    <td className="p-4">{lead.stage}</td>
                    <td className="p-4">
                      <span className={`badge-pill ${tempBadge(lead.lead_temperature)}`}>{lead.lead_temperature || "cold"}</span>
                    </td>
                    <td className="p-4 text-xs text-slate-500 mono">
                      {lead.external_last_synced_at ? new Date(lead.external_last_synced_at).toLocaleString() : "Not synced"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div className="p-3 rounded-lg bg-slate-50 border border-slate-100">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold">{label}</div>
      <div className="mt-1 font-bold text-slate-900">{String(value).replaceAll("_", " ")}</div>
    </div>
  );
}

function Metric({ label, value, tone = "blue" }) {
  const toneClass = tone === "green" ? "bg-green-500" : tone === "orange" ? "bg-orange-500" : tone === "slate" ? "bg-slate-500" : "bg-blue-500";
  return (
    <div className="p-3 rounded-lg bg-white border border-slate-200">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold">{label}</div>
      <div className="text-2xl font-black text-slate-900 mt-1">{value}</div>
      <div className={`mt-2 h-1 w-8 rounded-full ${toneClass}`} />
    </div>
  );
}
