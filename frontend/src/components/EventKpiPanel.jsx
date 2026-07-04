import React, { useEffect, useState, useCallback } from "react";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import Modal from "./Modal";
import { Plus, Upload, Info, Trash2 } from "lucide-react";
import { toast } from "sonner";

const CHANNELS = [
  "meta", "instagram", "youtube", "whatsapp", "email",
  "organic", "dark_ad", "referral", "manual", "other",
];

const KPI_NUM_FIELDS = [
  ["reach", "Reach"],
  ["impressions", "Impressions"],
  ["interactions", "Interactions"],
  ["clicks", "Clicks"],
  ["form_completions", "Form completions"],
  ["leads", "Leads"],
  ["meetings_booked", "Meetings booked"],
  ["meetings_attended", "Meetings attended"],
  ["no_shows", "No shows"],
  ["purchases", "Purchases"],
  ["spend", "Spend ($)"],
  ["revenue", "Revenue ($)"],
];

const EMPTY_KPI = {
  metric_date: new Date().toISOString().slice(0, 10),
  channel: "instagram",
  reach: 0, impressions: 0, interactions: 0, clicks: 0,
  form_completions: 0, leads: 0, meetings_booked: 0,
  meetings_attended: 0, no_shows: 0, purchases: 0,
  spend: 0, revenue: 0, notes: "",
};

const EXAMPLE_CSV_JSON = JSON.stringify(
  [
    {
      metric_date: "2026-07-04",
      channel: "instagram",
      reach: 1000,
      impressions: 1500,
      interactions: 120,
      clicks: 30,
      form_completions: 8,
      leads: 5,
      meetings_booked: 2,
      meetings_attended: 1,
      no_shows: 1,
      purchases: 1,
      spend: 250,
      revenue: 1200,
      notes: "Imported from verified report",
    },
  ],
  null,
  2,
);


export default function EventKpiPanel({ eventId, onChanged }) {
  const { t } = useI18n();
  const [rows, setRows] = useState([]);
  const [openAdd, setOpenAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_KPI);
  const [saving, setSaving] = useState(false);
  const [csvText, setCsvText] = useState(EXAMPLE_CSV_JSON);
  const [dryRun, setDryRun] = useState(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get(`/events/${eventId}/kpis`);
    setRows(data);
  }, [eventId]);

  useEffect(() => { load(); }, [load]);

  const submitAdd = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form };
      for (const [k] of KPI_NUM_FIELDS) payload[k] = Number(payload[k]) || 0;
      await api.post(`/events/${eventId}/kpis`, payload);
      toast.success("KPI record added");
      setOpenAdd(false);
      setForm(EMPTY_KPI);
      await load();
      onChanged && onChanged();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Validation failed");
    } finally {
      setSaving(false);
    }
  };

  const deleteRow = async (id) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    try {
      await api.delete(`/events/${eventId}/kpis/${id}`);
      await load();
      onChanged && onChanged();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Delete failed");
    }
  };

  const runDry = async () => {
    setDryRun(null);
    let parsed;
    try {
      parsed = JSON.parse(csvText);
    } catch {
      return toast.error("Invalid JSON — must be an array of KPI row objects");
    }
    if (!Array.isArray(parsed)) return toast.error("Expected a JSON array");
    try {
      const { data } = await api.post(
        `/events/${eventId}/kpis/csv/dry-run`,
        { rows: parsed },
      );
      setDryRun(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Dry-run failed");
    }
  };

  const runImport = async () => {
    if (!dryRun || dryRun.invalid_count > 0) return;
    setImporting(true);
    try {
      const parsed = JSON.parse(csvText);
      const { data } = await api.post(
        `/events/${eventId}/kpis/csv/import`,
        { rows: parsed },
      );
      toast.success(`Imported ${data.inserted_count} row(s)`);
      setDryRun(null);
      await load();
      onChanged && onChanged();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(
        typeof detail === "string" ? detail : (detail?.message || "Import failed"),
      );
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      {/* Verified KPI Records */}
      <div className="card-flat p-5 mb-8" data-testid="kpi-records-section">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-slate-900">
              Verified KPI Records
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              Manual or CSV-imported analytics. No external platform is called.
            </p>
          </div>
          <button
            onClick={() => setOpenAdd(true)}
            className="btn btn-primary"
            data-testid="kpi-add-btn"
          >
            <Plus className="w-4 h-4" /> Add KPI Record
          </button>
        </div>

        {rows.length === 0 ? (
          <div
            className="p-6 border border-dashed border-slate-200 rounded-lg text-center"
            data-testid="kpi-empty"
          >
            <div className="text-sm text-slate-700 font-medium">
              No verified KPI records yet.
            </div>
            <div className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
              Add manual KPI data or import a CSV export from Meta, YouTube,
              Formaloo, or GoHighLevel.
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-widest text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="text-start py-2 pe-3">Date</th>
                  <th className="text-start py-2 pe-3">Channel</th>
                  <th className="text-start py-2 pe-3">Source</th>
                  <th className="text-end py-2 pe-3">Reach</th>
                  <th className="text-end py-2 pe-3">Impr.</th>
                  <th className="text-end py-2 pe-3">Leads</th>
                  <th className="text-end py-2 pe-3">Purchases</th>
                  <th className="text-end py-2 pe-3">Spend</th>
                  <th className="text-end py-2 pe-3">Revenue</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    className="border-b border-slate-50"
                    data-testid={`kpi-row-${r.id}`}
                  >
                    <td className="py-2 pe-3 mono text-xs text-slate-700">{r.metric_date}</td>
                    <td className="py-2 pe-3">
                      <span className="badge-pill badge-blue">{r.channel}</span>
                    </td>
                    <td className="py-2 pe-3">
                      <span className="badge-pill badge-slate">{r.source_type}</span>
                    </td>
                    <td className="py-2 pe-3 text-end mono">{r.reach.toLocaleString()}</td>
                    <td className="py-2 pe-3 text-end mono">{r.impressions.toLocaleString()}</td>
                    <td className="py-2 pe-3 text-end mono">{r.leads.toLocaleString()}</td>
                    <td className="py-2 pe-3 text-end mono">{r.purchases.toLocaleString()}</td>
                    <td className="py-2 pe-3 text-end mono">${Number(r.spend).toLocaleString()}</td>
                    <td className="py-2 pe-3 text-end mono">${Number(r.revenue).toLocaleString()}</td>
                    <td className="py-2 text-end">
                      <button
                        onClick={() => deleteRow(r.id)}
                        className="btn btn-danger !p-1.5"
                        data-testid={`kpi-delete-${r.id}`}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* CSV Import Preview */}
      <div className="card-flat p-5 mb-8" data-testid="csv-import-section">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-slate-900">
              CSV Import Preview
            </h2>
            <p className="text-xs text-slate-500 mt-1 flex items-center gap-1">
              <Info className="w-3 h-3 text-orange-500" />
              CSV import is local validation only. No external platform is called.
            </p>
          </div>
        </div>

        <label className="field-label">Rows (JSON array)</label>
        <textarea
          className="field-input mono text-xs min-h-[180px]"
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
          data-testid="csv-textarea"
        />

        <div className="flex flex-wrap items-center gap-2 mt-3">
          <button
            onClick={runDry}
            className="btn btn-outline"
            data-testid="csv-validate-btn"
          >
            Validate Import
          </button>
          <button
            onClick={runImport}
            disabled={!dryRun || dryRun.invalid_count > 0 || importing}
            className="btn btn-primary"
            data-testid="csv-import-btn"
          >
            <Upload className="w-4 h-4" />
            {importing ? "Importing…" : "Import Valid Rows"}
          </button>
        </div>

        {dryRun && (
          <div
            className="mt-4 p-3 rounded-md border border-slate-200 bg-slate-50"
            data-testid="csv-dryrun-result"
          >
            <div className="flex flex-wrap gap-2 items-center mb-2">
              <span className="badge-pill badge-green">
                {dryRun.valid_count} valid
              </span>
              {dryRun.invalid_count > 0 && (
                <span className="badge-pill badge-red">
                  {dryRun.invalid_count} invalid
                </span>
              )}
            </div>
            {dryRun.invalid_count > 0 && (
              <ul className="text-xs text-red-800 space-y-1 mono mb-2" data-testid="csv-errors">
                {dryRun.row_errors.map((e, i) => (
                  <li key={i}>
                    row {e.row_index}: {e.error}
                  </li>
                ))}
              </ul>
            )}
            <div className="text-xs text-slate-700">
              <div className="font-semibold mb-1">Preview totals</div>
              <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mono">
                {Object.entries(dryRun.preview_totals).map(([k, v]) => (
                  <div key={k} className="p-2 bg-white rounded border border-slate-100">
                    <div className="text-[10px] uppercase text-slate-500">{k}</div>
                    <div className="font-bold text-slate-900">{v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <Modal
        open={openAdd}
        onClose={() => setOpenAdd(false)}
        title="Add KPI Record"
        testId="kpi-modal"
      >
        <form onSubmit={submitAdd} className="space-y-3" data-testid="kpi-form">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">Date</label>
              <input
                required type="date" className="field-input"
                value={form.metric_date}
                onChange={(e) => setForm({ ...form, metric_date: e.target.value })}
                data-testid="kpi-form-date"
              />
            </div>
            <div>
              <label className="field-label">Channel</label>
              <select
                className="field-input" value={form.channel}
                onChange={(e) => setForm({ ...form, channel: e.target.value })}
                data-testid="kpi-form-channel"
              >
                {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {KPI_NUM_FIELDS.map(([k, lbl]) => (
              <div key={k}>
                <label className="field-label">{lbl}</label>
                <input
                  type="number" min="0" className="field-input"
                  value={form[k]}
                  onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                  data-testid={`kpi-form-${k}`}
                />
              </div>
            ))}
          </div>
          <div>
            <label className="field-label">Notes</label>
            <textarea
              className="field-input min-h-[60px]" value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              data-testid="kpi-form-notes"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button" className="btn btn-outline"
              onClick={() => setOpenAdd(false)}
            >
              Cancel
            </button>
            <button
              type="submit" disabled={saving} className="btn btn-primary"
              data-testid="kpi-form-save"
            >
              Save
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}
