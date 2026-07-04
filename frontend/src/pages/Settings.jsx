import React, { useEffect, useState } from "react";
import { PageHeader } from "../components/ui-bits";
import Modal from "../components/Modal";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Plus, Trash2, Key, Share2 } from "lucide-react";
import { toast } from "sonner";

const LLM_PROVIDERS = [
  { v: "openai", label: "OpenAI (GPT-5.x)" },
  { v: "anthropic", label: "Anthropic (Claude)" },
  { v: "gemini", label: "Google (Gemini)" },
  { v: "gemma", label: "SmartLabs Gemma 4 Canary" },
];
const SOCIAL_PLATFORMS = ["meta", "instagram", "youtube", "tiktok", "linkedin", "x"];

export default function Settings() {
  const { t } = useI18n();
  const [tab, setTab] = useState("llm");
  const [keys, setKeys] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [openKey, setOpenKey] = useState(false);
  const [openSocial, setOpenSocial] = useState(false);
  const [kForm, setKForm] = useState({ provider: "gemma", api_key: "", model: "gemma4-26b-a4b-canary", label: "" });
  const [sForm, setSForm] = useState({ platform: "meta", handle: "", access_token: "", page_id: "" });

  const load = async () => {
    const [k, s] = await Promise.all([
      api.get("/settings/llm-keys"),
      api.get("/settings/social-accounts"),
    ]);
    setKeys(k.data); setAccounts(s.data);
  };
  useEffect(() => { load(); }, []);

  const saveKey = async (e) => {
    e.preventDefault();
    try {
      await api.post("/settings/llm-keys", kForm);
      toast.success(t("createdSuccess"));
      setOpenKey(false);
      setKForm({ provider: "gemma", api_key: "", model: "gemma4-26b-a4b-canary", label: "" });
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const saveSocial = async (e) => {
    e.preventDefault();
    try {
      await api.post("/settings/social-accounts", sForm);
      toast.success(t("createdSuccess"));
      setOpenSocial(false);
      setSForm({ platform: "meta", handle: "", access_token: "", page_id: "" });
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="settings-page">
      <PageHeader
        title={t("settings")}
        subtitle="Manage LLM API keys and social media account credentials — stored encrypted."
      />

      <div className="flex gap-2 border-b border-slate-200 mb-6">
        {[
          { k: "llm", label: t("llmKeys"), icon: Key },
          { k: "social", label: t("socialAccounts"), icon: Share2 },
        ].map((s) => {
          const I = s.icon;
          return (
            <button key={s.k}
              onClick={() => setTab(s.k)}
              className={`flex items-center gap-2 px-4 py-2.5 border-b-2 -mb-px text-sm font-semibold transition-colors ${
                tab === s.k ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
              data-testid={`settings-tab-${s.k}`}
            >
              <I className="w-4 h-4" />
              {s.label}
            </button>
          );
        })}
      </div>

      {tab === "llm" && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <div className="text-sm text-slate-500">
              Add provider keys to unlock full-power generation. Keys stay tenant-owned and are never shown after saving.
            </div>
            <button onClick={() => setOpenKey(true)} className="btn btn-primary" data-testid="llm-add-btn">
              <Plus className="w-4 h-4" /> {t("addKey")}
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="card-flat p-5">
              <div className="badge-pill badge-orange">Default</div>
              <div className="mt-2 text-lg font-bold text-slate-900">AI Provider Key</div>
              <div className="text-xs text-slate-500 mt-1">Works with OpenAI, Anthropic, Gemini, and SmartLabs Gemma.</div>
            </div>
            {keys.map((k) => (
              <div key={k.id} className="card-flat p-5" data-testid={`llm-key-${k.id}`}>
                <div className="flex items-center justify-between">
                  <span className="badge-pill badge-blue">{k.provider}</span>
                  <button onClick={async () => {
                    await api.delete(`/settings/llm-keys/${k.id}`);
                    load();
                  }} className="btn btn-danger !p-1.5" data-testid={`llm-key-delete-${k.id}`}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="mt-2 text-base font-semibold text-slate-900">
                  {k.label || k.provider}
                </div>
                <div className="mt-1 mono text-xs text-slate-500">{k.key_masked}</div>
                {k.model && <div className="mt-1 text-xs text-slate-500">Model: {k.model}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "social" && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <div className="text-sm text-slate-500">
              Tokens are encrypted at rest. Add page IDs when connecting business accounts.
            </div>
            <button onClick={() => setOpenSocial(true)} className="btn btn-primary" data-testid="social-add-btn">
              <Plus className="w-4 h-4" /> {t("addAccount")}
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {accounts.length === 0 && (
              <div className="col-span-full text-sm text-slate-500 py-6 text-center">
                {t("noData")}
              </div>
            )}
            {accounts.map((a) => (
              <div key={a.id} className="card-flat p-5" data-testid={`social-acct-${a.id}`}>
                <div className="flex items-center justify-between">
                  <span className="badge-pill badge-blue">{a.platform}</span>
                  <button onClick={async () => {
                    await api.delete(`/settings/social-accounts/${a.id}`);
                    load();
                  }} className="btn btn-danger !p-1.5">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="mt-2 text-base font-semibold text-slate-900">@{a.handle}</div>
                <div className="mt-1 mono text-xs text-slate-500">{a.token_masked}</div>
                {a.page_id && <div className="mt-1 text-xs text-slate-500">Page: {a.page_id}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      <Modal open={openKey} onClose={() => setOpenKey(false)} title={t("addKey")} testId="llm-modal">
        <form onSubmit={saveKey} className="space-y-3">
          <div>
            <label className="field-label">{t("provider")}</label>
            <select className="field-input" value={kForm.provider}
              onChange={(e) => setKForm({ ...kForm, provider: e.target.value })}
              data-testid="llm-form-provider">
              {LLM_PROVIDERS.map((p) => <option key={p.v} value={p.v}>{p.label}</option>)}
            </select>
          </div>
          <div>
            <label className="field-label">{t("apiKey")}</label>
            <input required type="password" className="field-input mono" value={kForm.api_key}
              onChange={(e) => setKForm({ ...kForm, api_key: e.target.value })}
              data-testid="llm-form-key" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("model")}</label>
              <input className="field-input mono" value={kForm.model}
                onChange={(e) => setKForm({ ...kForm, model: e.target.value })} />
            </div>
            <div>
              <label className="field-label">{t("label")}</label>
              <input className="field-input" value={kForm.label}
                onChange={(e) => setKForm({ ...kForm, label: e.target.value })} />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpenKey(false)}>{t("cancel")}</button>
            <button type="submit" className="btn btn-primary" data-testid="llm-form-save">{t("save")}</button>
          </div>
        </form>
      </Modal>

      <Modal open={openSocial} onClose={() => setOpenSocial(false)} title={t("addAccount")} testId="social-modal">
        <form onSubmit={saveSocial} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">{t("platform")}</label>
              <select className="field-input" value={sForm.platform}
                onChange={(e) => setSForm({ ...sForm, platform: e.target.value })}
                data-testid="social-form-platform">
                {SOCIAL_PLATFORMS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className="field-label">{t("handle")}</label>
              <input required className="field-input" value={sForm.handle}
                onChange={(e) => setSForm({ ...sForm, handle: e.target.value })}
                data-testid="social-form-handle" />
            </div>
          </div>
          <div>
            <label className="field-label">{t("accessToken")}</label>
            <input required type="password" className="field-input mono" value={sForm.access_token}
              onChange={(e) => setSForm({ ...sForm, access_token: e.target.value })}
              data-testid="social-form-token" />
          </div>
          <div>
            <label className="field-label">{t("pageId")}</label>
            <input className="field-input mono" value={sForm.page_id}
              onChange={(e) => setSForm({ ...sForm, page_id: e.target.value })} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpenSocial(false)}>{t("cancel")}</button>
            <button type="submit" className="btn btn-primary" data-testid="social-form-save">{t("save")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
