import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader, SectionTitle } from "../components/ui-bits";
import { api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Sparkles, Check, X, Save, Wand2 } from "lucide-react";
import { toast } from "sonner";

const PLATFORMS = ["meta", "instagram", "youtube", "tiktok", "whatsapp", "email"];
const GOALS = [
  { v: "max_reach", k: "goalReach" },
  { v: "conversion", k: "goalConversion" },
  { v: "engagement", k: "goalEngagement" },
];
const PROVIDERS = [
  { v: "openai", label: "OpenAI · GPT-5.2" },
  { v: "anthropic", label: "Anthropic · Claude Sonnet 4.6" },
  { v: "gemini", label: "Google · Gemini 3 Flash" },
];

export default function AIBuilder() {
  const { t, lang } = useI18n();
  const [params] = useSearchParams();
  const [events, setEvents] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [eventId, setEventId] = useState(params.get("event") || "");
  const [campaignId, setCampaignId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("openai");
  const [goal, setGoal] = useState("max_reach");
  const [selectedPlatforms, setSelectedPlatforms] = useState(["meta", "instagram", "youtube"]);
  const [audience, setAudience] = useState({ age_range: "25-40", gender: "all", geo: "Egypt", segment: "warm+cold" });
  const [n, setN] = useState(4);
  const [loading, setLoading] = useState(false);
  const [ideas, setIdeas] = useState([]);

  useEffect(() => {
    (async () => {
      const { data } = await api.get("/events");
      setEvents(data);
    })();
  }, []);

  useEffect(() => {
    if (!eventId) { setCampaigns([]); setCampaignId(""); return; }
    (async () => {
      const { data } = await api.get(`/events/${eventId}/campaigns`);
      setCampaigns(data);
      if (data.length && !campaignId) setCampaignId(data[0].id);
    })();
  }, [eventId]);

  const togglePlatform = (p) =>
    setSelectedPlatforms((s) => (s.includes(p) ? s.filter((x) => x !== p) : [...s, p]));

  const generate = async () => {
    if (!prompt.trim()) return toast.error("Add a prompt");
    setLoading(true);
    setIdeas([]);
    try {
      const { data } = await api.post("/posts/generate", {
        prompt, provider, goal, platforms: selectedPlatforms,
        audience, n, language: lang, campaign_id: campaignId || undefined,
        event_id: eventId || undefined,
      });
      const withStatus = (data.ideas || []).map((i, idx) => ({
        ...i, _idx: idx, _status: "pending",
      }));
      setIdeas(withStatus);
      if (withStatus.length === 0) toast.warning("AI returned no ideas — try a richer prompt.");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Generation failed");
    } finally {
      setLoading(false);
    }
  };

  const approve = async (idea) => {
    if (!campaignId) return toast.error("Select a campaign to save this post");
    try {
      await api.post("/posts", {
        campaign_id: campaignId,
        platform: idea.platform || "meta",
        format: idea.format || "text",
        hook: idea.hook,
        caption: idea.caption,
        cta: idea.cta,
        hashtags: idea.hashtags || [],
        reasoning: idea.reasoning,
        status: "approved",
      });
      setIdeas((arr) => arr.map((x) => x._idx === idea._idx ? { ...x, _status: "approved" } : x));
      toast.success("Approved & saved");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Error");
    }
  };

  const reject = (idea) => {
    setIdeas((arr) => arr.map((x) => x._idx === idea._idx ? { ...x, _status: "rejected" } : x));
  };

  const editField = (idx, field, val) => {
    setIdeas((arr) => arr.map((x) => x._idx === idx ? { ...x, [field]: val } : x));
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="ai-builder-page">
      <PageHeader
        title={t("aiBuilder")}
        subtitle="Generate multi-platform post ideas, tuned to your audience and platform algorithm."
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: config */}
        <div className="lg:col-span-5 space-y-4">
          <div className="card-flat p-5 space-y-3">
            <SectionTitle>Campaign</SectionTitle>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="field-label">Event</label>
                <select className="field-input" value={eventId}
                  onChange={(e) => setEventId(e.target.value)}
                  data-testid="ai-event-select">
                  <option value="">—</option>
                  {events.map((ev) => (
                    <option key={ev.id} value={ev.id}>{ev.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="field-label">{t("campaigns")}</label>
                <select className="field-input" value={campaignId}
                  onChange={(e) => setCampaignId(e.target.value)}
                  data-testid="ai-campaign-select">
                  <option value="">—</option>
                  {campaigns.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="card-flat p-5 space-y-3">
            <SectionTitle>{t("audience")}</SectionTitle>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="field-label">{t("ageRange")}</label>
                <input className="field-input" value={audience.age_range}
                  onChange={(e) => setAudience({ ...audience, age_range: e.target.value })} />
              </div>
              <div>
                <label className="field-label">{t("gender")}</label>
                <select className="field-input" value={audience.gender}
                  onChange={(e) => setAudience({ ...audience, gender: e.target.value })}>
                  <option value="all">All</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                </select>
              </div>
              <div>
                <label className="field-label">{t("geo")}</label>
                <input className="field-input" value={audience.geo}
                  onChange={(e) => setAudience({ ...audience, geo: e.target.value })} />
              </div>
              <div>
                <label className="field-label">{t("segment")}</label>
                <select className="field-input" value={audience.segment}
                  onChange={(e) => setAudience({ ...audience, segment: e.target.value })}>
                  <option value="warm+cold">Warm + Cold</option>
                  <option value="warm">Warm only</option>
                  <option value="cold">Cold only</option>
                  <option value="followers">Followers</option>
                  <option value="non-followers">Non-followers</option>
                </select>
              </div>
            </div>
          </div>

          <div className="card-flat p-5 space-y-3">
            <SectionTitle>Strategy</SectionTitle>
            <div>
              <label className="field-label">{t("goal")}</label>
              <div className="flex flex-wrap gap-2">
                {GOALS.map((g) => (
                  <button key={g.v}
                    onClick={() => setGoal(g.v)}
                    className={`btn ${goal === g.v ? "btn-primary" : "btn-outline"} !py-1.5 !px-3 text-xs`}
                    data-testid={`ai-goal-${g.v}`}
                  >
                    {t(g.k)}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="field-label">{t("platforms")}</label>
              <div className="flex flex-wrap gap-2">
                {PLATFORMS.map((p) => {
                  const on = selectedPlatforms.includes(p);
                  return (
                    <button key={p} onClick={() => togglePlatform(p)}
                      className={`btn ${on ? "btn-primary" : "btn-outline"} !py-1.5 !px-3 text-xs`}
                      data-testid={`ai-platform-${p}`}>
                      {p}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="field-label">{t("provider")}</label>
                <select className="field-input" value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  data-testid="ai-provider-select">
                  {PROVIDERS.map((p) => <option key={p.v} value={p.v}>{p.label}</option>)}
                </select>
              </div>
              <div>
                <label className="field-label">Ideas</label>
                <input type="number" min="1" max="8" className="field-input" value={n}
                  onChange={(e) => setN(Number(e.target.value))} />
              </div>
            </div>
          </div>

          <div className="card-flat p-5 space-y-3">
            <SectionTitle>{t("prompt")}</SectionTitle>
            <textarea
              className="field-input min-h-[130px]"
              placeholder={t("promptPlaceholder")}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              data-testid="ai-prompt-input"
            />
            <button
              onClick={generate}
              disabled={loading}
              className="btn btn-ai w-full !py-3"
              data-testid="ai-generate-btn"
            >
              {loading ? <><Wand2 className="w-4 h-4 animate-pulse" />{t("generating")}</> : <><Sparkles className="w-4 h-4" />{t("generate")}</>}
            </button>
          </div>
        </div>

        {/* Right: output */}
        <div className="lg:col-span-7 space-y-4">
          {ideas.length === 0 && !loading && (
            <div className="card-flat p-10 text-center" data-testid="ai-empty">
              <div className="w-14 h-14 rounded-full bg-orange-100 grid place-items-center mx-auto text-orange-600">
                <Sparkles className="w-6 h-6" />
              </div>
              <h3 className="mt-4 text-lg font-bold tracking-tight text-slate-900">
                Ready to spark ideas
              </h3>
              <p className="mt-1 text-sm text-slate-500 max-w-md mx-auto">
                Set your audience, pick platforms, describe the campaign — the AI will draft
                platform-native ideas with hooks, captions and CTAs.
              </p>
            </div>
          )}

          {loading && (
            <div className="card-flat p-10 text-center">
              <Wand2 className="w-6 h-6 text-orange-500 animate-pulse mx-auto" />
              <div className="mt-3 text-sm text-slate-600">{t("generating")}</div>
            </div>
          )}

          {ideas.map((idea) => (
            <div key={idea._idx}
              className={`card-flat p-5 transition-all ${
                idea._status === "approved" ? "border-green-300 bg-green-50/40"
                : idea._status === "rejected" ? "border-slate-200 opacity-50"
                : ""
              }`}
              data-testid={`ai-idea-${idea._idx}`}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="badge-pill badge-blue">{idea.platform}</span>
                  <span className="badge-pill badge-slate">{idea.format}</span>
                  {idea._status === "approved" && <span className="badge-pill badge-green">Approved</span>}
                </div>
                <div className="flex items-center gap-1">
                  {idea._status !== "approved" && (
                    <button onClick={() => approve(idea)}
                      className="btn btn-primary !py-1.5 !px-3 text-xs"
                      data-testid={`ai-idea-${idea._idx}-approve`}
                    >
                      <Check className="w-3.5 h-3.5" />
                      {t("approve")}
                    </button>
                  )}
                  <button onClick={() => reject(idea)}
                    className="btn btn-outline !py-1.5 !px-3 text-xs"
                    data-testid={`ai-idea-${idea._idx}-reject`}>
                    <X className="w-3.5 h-3.5" />
                    {t("reject")}
                  </button>
                </div>
              </div>

              <div className="space-y-3">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold mb-1">{t("hook")}</div>
                  <input className="field-input font-semibold text-slate-900"
                    value={idea.hook || ""}
                    onChange={(e) => editField(idea._idx, "hook", e.target.value)} />
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold mb-1">{t("caption")}</div>
                  <textarea className="field-input min-h-[90px]"
                    value={idea.caption || ""}
                    onChange={(e) => editField(idea._idx, "caption", e.target.value)} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold mb-1">{t("cta")}</div>
                    <input className="field-input"
                      value={idea.cta || ""}
                      onChange={(e) => editField(idea._idx, "cta", e.target.value)} />
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold mb-1">{t("hashtags")}</div>
                    <input className="field-input mono text-xs"
                      value={(idea.hashtags || []).join(" ")}
                      onChange={(e) => editField(idea._idx, "hashtags", e.target.value.split(/\s+/).filter(Boolean))} />
                  </div>
                </div>
                {idea.reasoning && (
                  <div className="p-3 rounded-md bg-slate-50 border border-slate-100">
                    <div className="text-[10px] uppercase tracking-widest text-orange-600 font-bold mb-1">
                      {t("reasoning")}
                    </div>
                    <div className="text-xs text-slate-700">{idea.reasoning}</div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
