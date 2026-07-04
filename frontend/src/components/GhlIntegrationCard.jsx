import React, { useEffect, useState, useCallback } from "react";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import Modal from "./Modal";
import { toast } from "sonner";
import { Plug, ShieldAlert, Plus, Trash2, RefreshCw, DownloadCloud } from "lucide-react";

const MAPPING_TYPES = [
  { v: "tag", label: "Tag" },
  { v: "pipeline_stage", label: "Pipeline stage" },
];
const TARGET_TYPES = [
  { v: "lead_status", label: "Lead status" },
  { v: "lead_temperature", label: "Lead temperature" },
];
const LEAD_STATUS = ["new", "form_filled", "booked", "purchased", "no_show", "lost", "follow_up_needed"];
const LEAD_TEMP = ["cold", "warm", "hot", "buyer"];
const DIRECTIONS = ["inbound", "outbound", "bidirectional"];

const EMPTY_MAPPING = {
  mapping_type: "tag", ghl_id: "", ghl_name: "",
  target_type: "lead_status", target_value: "form_filled",
  direction: "inbound",
};

export default function GhlIntegrationCard() {
  const { t } = useI18n();
  const [status, setStatus] = useState(null);
  const [mappings, setMappings] = useState([]);
  const [credOpen, setCredOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [existing, setExisting] = useState(null);
  const [credForm, setCredForm] = useState({
    api_key: "",
    location_id: "",
    base_url: "https://services.leadconnectorhq.com",
  });
  const [mForm, setMForm] = useState(EMPTY_MAPPING);
  const [syncing, setSyncing] = useState(false);
  const [previewResult, setPreviewResult] = useState(null);

  const load = useCallback(async () => {
    const [s, m, integ] = await Promise.all([
      api.get("/ghl/status"),
      api.get("/ghl/mappings"),
      api.get("/integrations"),
    ]);
    setStatus(s.data);
    setMappings(m.data);
    const ghlInt = (integ.data || []).find((i) => i.kind === "gohighlevel");
    setExisting(ghlInt || null);
    if (ghlInt) {
      setCredForm((f) => ({
        ...f,
        location_id: ghlInt?.config?.location_id || "",
        base_url: ghlInt?.config?.base_url || f.base_url,
      }));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveCredential = async (e) => {
    e.preventDefault();
    try {
      if (existing) {
        await api.delete(`/integrations/${existing.id}`);
      }
      await api.post("/integrations", {
        kind: "gohighlevel",
        label: "GoHighLevel CRM",
        api_key: credForm.api_key,
        config: {
          location_id: credForm.location_id,
          base_url: credForm.base_url,
        },
      });
      toast.success("Credential saved");
      setCredOpen(false);
      setCredForm({ ...credForm, api_key: "" });
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed");
    }
  };

  const saveMapping = async (e) => {
    e.preventDefault();
    try {
      await api.post("/ghl/mappings", mForm);
      toast.success("Mapping added");
      setMapOpen(false);
      setMForm(EMPTY_MAPPING);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Invalid mapping");
    }
  };

  const deleteMapping = async (id) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    await api.delete(`/ghl/mappings/${id}`);
    await load();
  };

  const runPreview = async () => {
    setPreviewResult(null);
    try {
      const { data } = await api.post("/ghl/pull-preview", { limit: 25 });
      setPreviewResult(data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Preview failed");
    }
  };

  const runSync = async () => {
    setSyncing(true);
    try {
      const { data } = await api.post("/ghl/pull-sync", { limit: 100 });
      if (data.status === "blocked") {
        toast.error(data.reason);
      } else {
        toast.success(
          `Inserted ${data.inserted_count} · Updated ${data.updated_count} · Mapped ${data.mapped_count}`,
        );
      }
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const statusPill = (s) => {
    if (s === "configured" || s === "ready") return "badge-green";
    if (s === "partial") return "badge-orange";
    return "badge-red";
  };

  const targetOptions = mForm.target_type === "lead_status" ? LEAD_STATUS : LEAD_TEMP;

  return (
    <div className="card-flat p-5" data-testid="ghl-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-md bg-slate-900 grid place-items-center text-white">
            <Plug className="w-4 h-4 text-orange-400" />
          </div>
          <div>
            <div className="font-bold text-slate-900">GoHighLevel CRM</div>
            <div className="text-xs text-slate-500">Source of truth for leads · Campaign OS is the reporting layer</div>
          </div>
        </div>
        <button
          onClick={() => setCredOpen(true)}
          className="btn btn-primary !py-1.5 !px-3 text-xs"
          data-testid="ghl-save-credential-btn"
        >
          {existing ? "Update credential" : "Save credential"}
        </button>
      </div>

      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div className="p-2 rounded-md bg-slate-50 border border-slate-100">
          <div className="text-[10px] uppercase text-slate-500">Credential</div>
          <span className={`badge-pill ${statusPill(status?.credential_status)} mt-1 inline-block`} data-testid="ghl-status-credential">
            {status?.credential_status || "…"}
          </span>
        </div>
        <div className="p-2 rounded-md bg-slate-50 border border-slate-100">
          <div className="text-[10px] uppercase text-slate-500">Location ID</div>
          <span className={`badge-pill ${statusPill(status?.location_id_status)} mt-1 inline-block`} data-testid="ghl-status-location">
            {status?.location_id_status || "…"}
          </span>
        </div>
        <div className="p-2 rounded-md bg-slate-50 border border-slate-100">
          <div className="text-[10px] uppercase text-slate-500">Mappings</div>
          <span className={`badge-pill ${statusPill(status?.mapping_status)} mt-1 inline-block`} data-testid="ghl-status-mappings">
            {status?.mapping_status || "…"}
          </span>
        </div>
        <div className="p-2 rounded-md bg-slate-50 border border-slate-100">
          <div className="text-[10px] uppercase text-slate-500">Read sync</div>
          <span className={`badge-pill ${status?.read_sync_enabled ? "badge-green" : "badge-red"} mt-1 inline-block`} data-testid="ghl-status-read-sync">
            {status?.read_sync_enabled ? "enabled" : "off"}
          </span>
        </div>
      </div>

      {status?.required_actions?.length > 0 && (
        <div className="mt-3 p-3 bg-orange-50 border border-orange-200 rounded-md" data-testid="ghl-required-actions">
          <div className="flex items-center gap-2 text-orange-800 font-semibold text-sm mb-1">
            <ShieldAlert className="w-4 h-4" /> Required actions
          </div>
          <ul className="text-xs text-orange-900 space-y-0.5 list-disc list-inside">
            {status.required_actions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}

      {/* Mappings */}
      <div className="mt-5 border-t border-slate-100 pt-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-semibold text-slate-900">Tag & Stage Mappings</div>
          <button onClick={() => setMapOpen(true)} className="btn btn-outline !py-1 !px-2 text-xs" data-testid="ghl-add-mapping-btn">
            <Plus className="w-3 h-3" /> Add mapping
          </button>
        </div>
        {mappings.length === 0 ? (
          <div className="text-xs text-slate-500 py-3">
            No mappings yet — add tag or pipeline-stage rules to translate GHL data into local statuses.
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase text-slate-500">
              <tr className="border-b border-slate-100">
                <th className="text-start py-1.5">Type</th>
                <th className="text-start py-1.5">GHL name / id</th>
                <th className="text-start py-1.5">Direction</th>
                <th className="text-start py-1.5">→ Target</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((m) => (
                <tr key={m.id} className="border-b border-slate-50" data-testid={`ghl-mapping-${m.id}`}>
                  <td className="py-1.5"><span className="badge-pill badge-blue">{m.mapping_type}</span></td>
                  <td className="py-1.5 mono">{m.ghl_name}{m.ghl_id ? ` (${m.ghl_id})` : ""}</td>
                  <td className="py-1.5">{m.direction}</td>
                  <td className="py-1.5"><span className="badge-pill badge-slate">{m.target_type}:{m.target_value}</span></td>
                  <td className="py-1.5 text-end">
                    <button onClick={() => deleteMapping(m.id)} className="btn btn-danger !p-1" data-testid={`ghl-mapping-delete-${m.id}`}>
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Actions */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button onClick={load} className="btn btn-outline !py-1.5 !px-3 text-xs" data-testid="ghl-check-status-btn">
          <RefreshCw className="w-3 h-3" /> Check status
        </button>
        <button onClick={runPreview} className="btn btn-outline !py-1.5 !px-3 text-xs" data-testid="ghl-preview-btn">
          Preview pull
        </button>
        <button onClick={runSync} disabled={syncing} className="btn btn-primary !py-1.5 !px-3 text-xs" data-testid="ghl-sync-btn">
          <DownloadCloud className="w-3 h-3" /> {syncing ? "Syncing…" : "Sync from GHL"}
        </button>
      </div>

      {previewResult && (
        <div className="mt-3 p-3 bg-slate-50 border border-slate-100 rounded-md text-xs" data-testid="ghl-preview-result">
          {previewResult.status === "blocked" ? (
            <div className="text-orange-800">
              <div className="font-semibold">Blocked: {previewResult.reason}</div>
              <div>{previewResult.required_action}</div>
            </div>
          ) : (
            <>
              <div className="font-semibold text-slate-900 mb-1">{previewResult.count} preview lead(s)</div>
              <div className="max-h-48 overflow-auto space-y-1 mono text-[11px]">
                {previewResult.preview.slice(0, 10).map((p, i) => (
                  <div key={i} className="p-1 bg-white border border-slate-100 rounded">
                    {p.name} · {p.email || p.phone || "—"} · {p.mapped_lead_status || "unmapped"} / {p.mapped_lead_temperature || "?"}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Credential modal */}
      <Modal open={credOpen} onClose={() => setCredOpen(false)} title="GoHighLevel credential" testId="ghl-cred-modal">
        <form onSubmit={saveCredential} className="space-y-3" data-testid="ghl-cred-form">
          <div>
            <label className="field-label">API key</label>
            <input required type="password" className="field-input mono"
              value={credForm.api_key}
              onChange={(e) => setCredForm({ ...credForm, api_key: e.target.value })}
              placeholder={existing ? "•••••••• (replace)" : ""}
              data-testid="ghl-cred-api-key" />
          </div>
          <div>
            <label className="field-label">Location ID</label>
            <input required className="field-input mono"
              value={credForm.location_id}
              onChange={(e) => setCredForm({ ...credForm, location_id: e.target.value })}
              data-testid="ghl-cred-location" />
          </div>
          <div>
            <label className="field-label">Base URL (optional)</label>
            <input className="field-input mono"
              value={credForm.base_url}
              onChange={(e) => setCredForm({ ...credForm, base_url: e.target.value })} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setCredOpen(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary" data-testid="ghl-cred-save">Save credential</button>
          </div>
        </form>
      </Modal>

      {/* Mapping modal */}
      <Modal open={mapOpen} onClose={() => setMapOpen(false)} title="Add mapping" testId="ghl-map-modal">
        <form onSubmit={saveMapping} className="space-y-3" data-testid="ghl-map-form">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">Mapping type</label>
              <select className="field-input" value={mForm.mapping_type}
                onChange={(e) => setMForm({ ...mForm, mapping_type: e.target.value })}
                data-testid="ghl-map-type">
                {MAPPING_TYPES.map((x) => <option key={x.v} value={x.v}>{x.label}</option>)}
              </select>
            </div>
            <div>
              <label className="field-label">Direction</label>
              <select className="field-input" value={mForm.direction}
                onChange={(e) => setMForm({ ...mForm, direction: e.target.value })}>
                {DIRECTIONS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">GHL name</label>
              <input required className="field-input" value={mForm.ghl_name}
                onChange={(e) => setMForm({ ...mForm, ghl_name: e.target.value })}
                data-testid="ghl-map-name" />
            </div>
            <div>
              <label className="field-label">GHL id (optional)</label>
              <input className="field-input mono" value={mForm.ghl_id}
                onChange={(e) => setMForm({ ...mForm, ghl_id: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">Target type</label>
              <select className="field-input" value={mForm.target_type}
                onChange={(e) => setMForm({
                  ...mForm,
                  target_type: e.target.value,
                  target_value: e.target.value === "lead_status" ? LEAD_STATUS[0] : LEAD_TEMP[0],
                })}
                data-testid="ghl-map-target-type">
                {TARGET_TYPES.map((x) => <option key={x.v} value={x.v}>{x.label}</option>)}
              </select>
            </div>
            <div>
              <label className="field-label">Target value</label>
              <select className="field-input" value={mForm.target_value}
                onChange={(e) => setMForm({ ...mForm, target_value: e.target.value })}
                data-testid="ghl-map-target-value">
                {targetOptions.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setMapOpen(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary" data-testid="ghl-map-save">Add mapping</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
