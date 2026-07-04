import React, { useEffect, useState, useCallback } from "react";
import { api } from "../lib/api";
import Modal from "./Modal";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

/**
 * Generic planner card.
 * Props:
 *  - title: string
 *  - eventId: string
 *  - resource: URL path segment (e.g. "content-requirements")
 *  - fields: [{name,label,type:'text'|'number'|'date'|'textarea'|'select', options?:string[]}]
 *  - listCols: [{name,label,render?:(r)=>node}]
 *  - statusField: field name to render as a badge (optional)
 *  - defaultForm: initial form values
 *  - testIdKey: short prefix for data-testid
 *  - emptyCta: text on empty state
 */
export default function PlannerCard({
  title,
  eventId,
  resource,
  fields,
  listCols,
  statusField,
  defaultForm,
  testIdKey,
  emptyCta,
}) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(defaultForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get(`/events/${eventId}/${resource}`);
    setItems(data);
  }, [eventId, resource]);
  useEffect(() => { load(); }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form };
      // coerce number fields
      for (const f of fields) {
        if (f.type === "number") payload[f.name] = Number(payload[f.name]) || 0;
      }
      await api.post(`/events/${eventId}/${resource}`, payload);
      toast.success("Saved");
      setOpen(false);
      setForm(defaultForm);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed");
    } finally {
      setSaving(false);
    }
  };

  const del = async (id) => {
    if (!window.confirm("Delete this?")) return;
    try {
      await api.delete(`/events/${eventId}/${resource}/${id}`);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Delete failed");
    }
  };

  const statusPill = (v) => {
    const map = {
      approved: "badge-green", done: "badge-green", active: "badge-green",
      pending_review: "badge-orange", planned: "badge-blue", draft: "badge-slate",
      in_progress: "badge-blue", open: "badge-blue",
      blocked: "badge-red", changes_requested: "badge-red", paused: "badge-orange",
      completed: "badge-green",
    };
    return map[v] || "badge-slate";
  };

  return (
    <div className="card-flat p-5" data-testid={`planner-${testIdKey}`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-base font-bold tracking-tight text-slate-900">{title}</h3>
        <button
          onClick={() => setOpen(true)}
          className="btn btn-primary !py-1.5 !px-3 text-xs"
          data-testid={`planner-${testIdKey}-add`}
        >
          <Plus className="w-3 h-3" /> Add
        </button>
      </div>

      {items.length === 0 ? (
        <div className="text-xs text-slate-500 py-4 text-center border border-dashed border-slate-200 rounded-md" data-testid={`planner-${testIdKey}-empty`}>
          {emptyCta}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase text-slate-500">
              <tr className="border-b border-slate-100">
                {listCols.map((c) => <th key={c.name} className="text-start py-1.5 pe-3">{c.label}</th>)}
                {statusField && <th className="py-1.5 pe-3">Status</th>}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b border-slate-50" data-testid={`planner-${testIdKey}-row-${r.id}`}>
                  {listCols.map((c) => (
                    <td key={c.name} className="py-1.5 pe-3">
                      {c.render ? c.render(r) : (r[c.name] || "—")}
                    </td>
                  ))}
                  {statusField && (
                    <td className="py-1.5 pe-3">
                      <span className={`badge-pill ${statusPill(r[statusField])}`}>{r[statusField]}</span>
                    </td>
                  )}
                  <td className="py-1.5 text-end">
                    <button onClick={() => del(r.id)} className="btn btn-danger !p-1" data-testid={`planner-${testIdKey}-delete-${r.id}`}>
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={title} testId={`planner-${testIdKey}-modal`}>
        <form onSubmit={submit} className="space-y-3" data-testid={`planner-${testIdKey}-form`}>
          <div className="grid grid-cols-2 gap-3">
            {fields.map((f) => (
              <div key={f.name} className={f.wide ? "col-span-2" : ""}>
                <label className="field-label">{f.label}</label>
                {f.type === "select" ? (
                  <select
                    className="field-input" value={form[f.name] || ""}
                    onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
                    data-testid={`planner-${testIdKey}-field-${f.name}`}
                  >
                    {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : f.type === "textarea" ? (
                  <textarea
                    className="field-input min-h-[60px]" value={form[f.name] || ""}
                    onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
                    data-testid={`planner-${testIdKey}-field-${f.name}`}
                  />
                ) : (
                  <input
                    type={f.type || "text"} className="field-input"
                    value={form[f.name] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
                    required={f.required}
                    data-testid={`planner-${testIdKey}-field-${f.name}`}
                  />
                )}
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" disabled={saving} className="btn btn-primary" data-testid={`planner-${testIdKey}-save`}>Save</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
