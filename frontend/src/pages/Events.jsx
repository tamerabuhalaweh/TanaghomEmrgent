import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, currency } from "../components/ui-bits";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import Modal from "../components/Modal";
import { Plus, MapPin, Calendar as CalendarIcon, Trash2, ArrowRight } from "lucide-react";
import { toast } from "sonner";

const TYPE_LABELS = {
  motaz_live: "Motaz Live",
  excellence_camp: "Excellence Camp",
  business_camp: "Business Camp",
  virtual_ramadan: "Virtual — Ramadan",
  custom: "Custom",
};

const COVER_DEFAULTS = {
  motaz_live:
    "https://images.unsplash.com/photo-1762968274962-20c12e6e8ecd?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHwxfHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85",
  excellence_camp:
    "https://images.unsplash.com/photo-1781029711351-e915512bf69c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHw0fHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85",
  business_camp:
    "https://images.unsplash.com/photo-1781029711351-e915512bf69c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHw0fHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85",
  virtual_ramadan:
    "https://images.unsplash.com/photo-1762968274962-20c12e6e8ecd?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHwxfHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85",
  custom:
    "https://images.unsplash.com/photo-1781029711351-e915512bf69c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2NDF8MHwxfHNlYXJjaHw0fHxidXNpbmVzcyUyMGNvbmZlcmVuY2UlMjBzdGFnZXxlbnwwfHx8fDE3ODMxNTI3MTB8MA&ixlib=rb-4.1.0&q=85",
};

const EMPTY = {
  name: "",
  type: "motaz_live",
  description: "",
  start_date: "",
  end_date: "",
  location: "",
  budget_planned: 0,
  ticket_price: 0,
  cover_image: "",
};

export default function Events() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const { data } = await api.get("/events");
    setItems(data);
  };

  useEffect(() => {
    load();
  }, []);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        ...form,
        budget_planned: Number(form.budget_planned) || 0,
        ticket_price: Number(form.ticket_price) || 0,
        cover_image: form.cover_image || COVER_DEFAULTS[form.type],
      };
      await api.post("/events", payload);
      toast.success(t("createdSuccess"));
      setOpen(false);
      setForm(EMPTY);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    } finally {
      setSaving(false);
    }
  };

  const del = async (id) => {
    if (!window.confirm(t("deleteConfirm"))) return;
    await api.delete(`/events/${id}`);
    load();
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="events-page">
      <PageHeader
        title={t("events")}
        subtitle={t("perEventDashboard")}
        actions={
          <button
            onClick={() => setOpen(true)}
            className="btn btn-primary"
            data-testid="events-create-btn"
          >
            <Plus className="w-4 h-4" />
            {t("createEvent")}
          </button>
        }
      />

      {items.length === 0 && (
        <div className="card-flat p-10 text-center text-slate-500" data-testid="events-empty">
          {t("noData")}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {items.map((ev, i) => (
          <div
            key={ev.id}
            className={`card-flat overflow-hidden rise-in rise-in-${(i % 6) + 1}`}
            data-testid={`event-card-${ev.id}`}
          >
            <div className="relative h-40 overflow-hidden grain">
              <img
                src={ev.cover_image || COVER_DEFAULTS[ev.type]}
                alt={ev.name}
                className="w-full h-full object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/25 to-transparent" />
              <div className="absolute inset-x-4 bottom-3 text-white">
                <div className="text-[10px] uppercase tracking-[0.18em] text-orange-300 font-bold">
                  {TYPE_LABELS[ev.type] || ev.type}
                </div>
                <div className="text-lg font-bold tracking-tight leading-tight">
                  {ev.name}
                </div>
              </div>
            </div>
            <div className="p-5 space-y-3">
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <CalendarIcon className="w-3.5 h-3.5" />
                <span className="mono">{ev.start_date}</span>
                {ev.end_date && (
                  <>
                    <span>→</span>
                    <span className="mono">{ev.end_date}</span>
                  </>
                )}
              </div>
              {ev.location && (
                <div className="flex items-center gap-2 text-xs text-slate-600">
                  <MapPin className="w-3.5 h-3.5" />
                  <span>{ev.location}</span>
                </div>
              )}
              <div className="flex items-center justify-between pt-2">
                <div>
                  <div className="text-[10px] uppercase text-slate-500 tracking-widest">
                    {t("budgetPlanned")}
                  </div>
                  <div className="font-bold text-slate-900">
                    {currency(ev.budget_planned)}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => del(ev.id)}
                    className="btn btn-danger !p-2"
                    data-testid={`event-delete-${ev.id}`}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => navigate(`/events/${ev.id}`)}
                    className="btn btn-primary !py-1.5"
                    data-testid={`event-open-${ev.id}`}
                  >
                    {t("view")}
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title={t("newEvent")} testId="event-modal">
        <form onSubmit={save} className="space-y-3" data-testid="event-form">
          <div>
            <label className="field-label">{t("eventName")}</label>
            <input
              required
              className="field-input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              data-testid="event-form-name"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("eventType")}</label>
              <select
                className="field-input"
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                data-testid="event-form-type"
              >
                {Object.entries(TYPE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label">{t("location")}</label>
              <input
                className="field-input"
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
                data-testid="event-form-location"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("startDate")}</label>
              <input
                required
                type="date"
                className="field-input"
                value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                data-testid="event-form-start"
              />
            </div>
            <div>
              <label className="field-label">{t("endDate")}</label>
              <input
                type="date"
                className="field-input"
                value={form.end_date}
                onChange={(e) => setForm({ ...form, end_date: e.target.value })}
                data-testid="event-form-end"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("budgetPlanned")} ($)</label>
              <input
                type="number"
                min="0"
                className="field-input"
                value={form.budget_planned}
                onChange={(e) => setForm({ ...form, budget_planned: e.target.value })}
                data-testid="event-form-budget"
              />
            </div>
            <div>
              <label className="field-label">{t("ticketPrice")} ($)</label>
              <input
                type="number"
                min="0"
                className="field-input"
                value={form.ticket_price}
                onChange={(e) => setForm({ ...form, ticket_price: e.target.value })}
                data-testid="event-form-price"
              />
            </div>
          </div>
          <div>
            <label className="field-label">{t("description")}</label>
            <textarea
              className="field-input min-h-[80px]"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              data-testid="event-form-description"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setOpen(false)}
              data-testid="event-form-cancel"
            >
              {t("cancel")}
            </button>
            <button
              disabled={saving}
              type="submit"
              className="btn btn-primary"
              data-testid="event-form-save"
            >
              {t("save")}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
