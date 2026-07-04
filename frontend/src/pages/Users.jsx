import React, { useEffect, useState } from "react";
import { PageHeader } from "../components/ui-bits";
import Modal from "../components/Modal";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

const ROLES = ["admin", "marketing", "sales", "viewer"];

const EMPTY = { name: "", email: "", password: "", role: "marketing" };

export default function Users() {
  const { t } = useI18n();
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);

  const load = async () => {
    const { data } = await api.get("/users");
    setUsers(data);
  };
  useEffect(() => { load(); }, []);

  const save = async (e) => {
    e.preventDefault();
    try {
      await api.post("/users", form);
      toast.success(t("createdSuccess"));
      setOpen(false); setForm(EMPTY); load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const del = async (id) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    try {
      await api.delete(`/users/${id}`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const toggle = async (u) => {
    await api.patch(`/users/${u.id}`, { is_active: !u.is_active });
    load();
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="users-page">
      <PageHeader
        title={t("users")}
        subtitle="Add users and assign granular permissions."
        actions={
          <button onClick={() => setOpen(true)} className="btn btn-primary" data-testid="users-new-btn">
            <Plus className="w-4 h-4" /> {t("newUser")}
          </button>
        }
      />

      <div className="card-flat overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-[10px] uppercase tracking-widest text-slate-500 bg-slate-50">
            <tr>
              <th className="text-start py-3 px-5">{t("name")}</th>
              <th className="text-start py-3 px-5">{t("email")}</th>
              <th className="text-start py-3 px-5">{t("role")}</th>
              <th className="text-start py-3 px-5">Status</th>
              <th className="py-3 px-5"></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-slate-100" data-testid={`user-row-${u.id}`}>
                <td className="py-3 px-5 font-semibold text-slate-900">{u.name}</td>
                <td className="py-3 px-5 mono text-xs text-slate-600">{u.email}</td>
                <td className="py-3 px-5">
                  <span className="badge-pill badge-blue">{u.role}</span>
                </td>
                <td className="py-3 px-5">
                  <button onClick={() => toggle(u)}
                    className={`badge-pill ${u.is_active ? "badge-green" : "badge-red"}`}
                    data-testid={`user-toggle-${u.id}`}>
                    {u.is_active ? t("active") : t("disabled")}
                  </button>
                </td>
                <td className="py-3 px-5 text-end">
                  <button onClick={() => del(u.id)}
                    className="btn btn-danger !p-1.5"
                    data-testid={`user-delete-${u.id}`}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title={t("newUser")} testId="user-modal">
        <form onSubmit={save} className="space-y-3">
          <div>
            <label className="field-label">{t("name")}</label>
            <input required className="field-input" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              data-testid="user-form-name" />
          </div>
          <div>
            <label className="field-label">{t("email")}</label>
            <input required type="email" className="field-input" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              data-testid="user-form-email" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("password")}</label>
              <input required type="password" className="field-input" value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                data-testid="user-form-password" />
            </div>
            <div>
              <label className="field-label">{t("role")}</label>
              <select className="field-input" value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                data-testid="user-form-role">
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpen(false)}>{t("cancel")}</button>
            <button type="submit" className="btn btn-primary" data-testid="user-form-save">{t("save")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
