import React, { useEffect, useState } from "react";
import { PageHeader } from "../components/ui-bits";
import Modal from "../components/Modal";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Plus, Trash2, Plug, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";

const KINDS = [
  { v: "gohighlevel", label: "GoHighLevel CRM", desc: "Sync leads, tags, and automation workflows." },
  { v: "zapier", label: "Zapier Webhook", desc: "Pipe events into 6000+ apps." },
  { v: "webhook", label: "Generic Webhook", desc: "Post lead/campaign events anywhere." },
];

export default function Integrations() {
  const { t } = useI18n();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ kind: "gohighlevel", label: "GoHighLevel", api_key: "", webhook_url: "" });

  const load = async () => {
    const { data } = await api.get("/integrations");
    setItems(data);
  };
  useEffect(() => { load(); }, []);

  const save = async (e) => {
    e.preventDefault();
    try {
      await api.post("/integrations", form);
      toast.success(t("createdSuccess"));
      setOpen(false);
      setForm({ kind: "gohighlevel", label: "GoHighLevel", api_key: "", webhook_url: "" });
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const del = async (id) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    await api.delete(`/integrations/${id}`);
    load();
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="integrations-page">
      <PageHeader
        title={t("integrations")}
        subtitle="Connect external CRMs and automation platforms."
        actions={
          <button onClick={() => setOpen(true)} className="btn btn-primary" data-testid="integrations-new-btn">
            <Plus className="w-4 h-4" /> {t("addIntegration")}
          </button>
        }
      />

      {/* Catalog */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {KINDS.map((k) => {
          const active = items.find((i) => i.kind === k.v);
          return (
            <div key={k.v} className="card-flat p-5" data-testid={`integration-catalog-${k.v}`}>
              <div className="flex items-center justify-between">
                <div className="w-10 h-10 rounded-md bg-slate-900 grid place-items-center text-white">
                  <Plug className="w-4 h-4 text-orange-400" />
                </div>
                {active && (
                  <span className="badge-pill badge-green flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Connected
                  </span>
                )}
              </div>
              <div className="mt-4 font-bold text-slate-900">{k.label}</div>
              <p className="mt-1 text-xs text-slate-500">{k.desc}</p>
              <button
                onClick={() => {
                  setForm({ kind: k.v, label: k.label, api_key: "", webhook_url: "" });
                  setOpen(true);
                }}
                className={`mt-4 btn ${active ? "btn-outline" : "btn-primary"} !py-1.5 !px-3 text-xs w-full justify-center`}
                data-testid={`integration-catalog-${k.v}-connect`}
              >
                {active ? "Reconnect" : t("connectedTo").replace(t("connectedTo"), "Connect")}
              </button>
            </div>
          );
        })}
      </div>

      {/* Active */}
      <div className="card-flat overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 text-[10px] uppercase tracking-widest text-slate-500 font-bold">
          Active Integrations
        </div>
        {items.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">{t("noData")}</div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className="border-t border-slate-100" data-testid={`integration-row-${i.id}`}>
                  <td className="py-3 px-5 font-semibold text-slate-900">{i.label}</td>
                  <td className="py-3 px-5"><span className="badge-pill badge-blue">{i.kind}</span></td>
                  <td className="py-3 px-5 mono text-xs text-slate-500">{i.api_key_masked || i.webhook_url || "—"}</td>
                  <td className="py-3 px-5 text-end">
                    <button onClick={() => del(i.id)} className="btn btn-danger !p-1.5"
                      data-testid={`integration-delete-${i.id}`}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title={t("addIntegration")} testId="integration-modal">
        <form onSubmit={save} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("integrationKind")}</label>
              <select className="field-input" value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}
                data-testid="integration-form-kind">
                {KINDS.map((k) => <option key={k.v} value={k.v}>{k.label}</option>)}
              </select>
            </div>
            <div>
              <label className="field-label">{t("label")}</label>
              <input required className="field-input" value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                data-testid="integration-form-label" />
            </div>
          </div>
          <div>
            <label className="field-label">{t("apiKey")}</label>
            <input type="password" className="field-input mono" value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              data-testid="integration-form-key" />
          </div>
          <div>
            <label className="field-label">{t("webhookUrl")}</label>
            <input className="field-input mono text-xs" value={form.webhook_url}
              onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
              data-testid="integration-form-webhook" />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpen(false)}>{t("cancel")}</button>
            <button type="submit" className="btn btn-primary" data-testid="integration-form-save">{t("save")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
