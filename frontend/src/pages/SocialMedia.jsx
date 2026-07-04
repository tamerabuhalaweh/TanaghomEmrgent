import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader, SectionTitle } from "../components/ui-bits";
import Modal from "../components/Modal";
import { api } from "../lib/api";
import { CalendarClock, CheckCircle2, Plug, RefreshCw, Send, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

function statusBadge(status) {
  if (status === "ready_for_scheduling") return "badge-blue";
  if (status === "approved") return "badge-green";
  if (status === "rejected") return "badge-red";
  return "badge-slate";
}

export default function SocialMedia() {
  const [posts, setPosts] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [openPostiz, setOpenPostiz] = useState(false);
  const [form, setForm] = useState({
    api_key: "",
    base_url: "https://postiz.163-123-180-104.sslip.io",
    workspace_id: "",
  });
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [postRes, integrationRes] = await Promise.all([
        api.get("/posts"),
        api.get("/integrations"),
      ]);
      setPosts(postRes.data || []);
      setIntegrations(integrationRes.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not load social media workspace");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const postiz = integrations.find((item) => item.kind === "postiz");
  const readyPosts = posts.filter((post) => post.status === "ready_for_scheduling");
  const approvedPosts = posts.filter((post) => post.status === "approved");
  const draftPosts = posts.filter((post) => !post.status || post.status === "draft");

  const savePostiz = async (e) => {
    e.preventDefault();
    try {
      if (postiz) await api.delete(`/integrations/${postiz.id}`);
      await api.post("/integrations", {
        kind: "postiz",
        label: "Postiz Scheduling",
        api_key: form.api_key,
        webhook_url: form.base_url,
        config: {
          base_url: form.base_url,
          workspace_id: form.workspace_id,
        },
      });
      toast.success("Postiz credential saved");
      setOpenPostiz(false);
      setForm({ ...form, api_key: "" });
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not save Postiz setup");
    }
  };

  const markReady = async (post) => {
    try {
      await api.patch(`/posts/${post.id}`, { status: "ready_for_scheduling" });
      toast.success("Marked ready for scheduling");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not update post");
    }
  };

  const syncToPostiz = async (post) => {
    if (!postiz) {
      toast.error("Save Postiz credentials first. No external call was made.");
      return;
    }
    await markReady(post);
    toast.message("Postiz live sync is not enabled yet. The post is prepared and ready for the future connector.");
  };

  const totals = useMemo(() => ({
    ready: readyPosts.length,
    approved: approvedPosts.length,
    draft: draftPosts.length,
    total: posts.length,
  }), [posts]);

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="social-media-page">
      <PageHeader
        title="Social Media"
        subtitle="Operate approved content from one place. Review posts, prepare scheduling packages, and connect Postiz without jumping between tools."
        actions={
          <button className="btn btn-primary" onClick={() => setOpenPostiz(true)} data-testid="postiz-setup-btn">
            <Plug className="w-4 h-4" /> {postiz ? "Update Postiz" : "Connect Postiz"}
          </button>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
        <div className="lg:col-span-8 card-flat p-5">
          <SectionTitle>Scheduling Control</SectionTitle>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SocialMetric label="Total posts" value={totals.total} />
            <SocialMetric label="Ready" value={totals.ready} tone="blue" />
            <SocialMetric label="Approved" value={totals.approved} tone="green" />
            <SocialMetric label="Drafts" value={totals.draft} tone="slate" />
          </div>
          <div className="mt-5 p-4 rounded-lg bg-slate-50 border border-slate-100">
            <div className="flex items-start gap-3">
              <ShieldAlert className="w-5 h-5 text-orange-500 mt-0.5" />
              <div>
                <div className="font-bold text-slate-900">External publishing is controlled</div>
                <p className="text-sm text-slate-600 mt-1">
                  This workspace prepares posts for Postiz. Live scheduling/publishing requires a validated Postiz connector and explicit approval.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-4 card-flat p-5" data-testid="postiz-status-card">
          <SectionTitle>Postiz Status</SectionTitle>
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-lg bg-slate-900 text-white grid place-items-center">
              <CalendarClock className="w-5 h-5 text-orange-400" />
            </div>
            <div>
              <div className="font-bold text-slate-900">Scheduling service</div>
              <div className="text-xs text-slate-500">Postiz connector readiness</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs">
            <StatusBox label="Credential" value={postiz ? "saved" : "missing"} ok={Boolean(postiz)} />
            <StatusBox label="Validation" value={postiz?.validated ? "validated" : "not validated"} ok={postiz?.validated} />
            <StatusBox label="Live sync" value={postiz?.live_sync_enabled ? "on" : "off"} ok={postiz?.live_sync_enabled} />
            <StatusBox label="Ready posts" value={totals.ready} ok={totals.ready > 0} />
          </div>
          {postiz ? (
            <div className="mt-4 text-xs text-slate-500">
              Credential is stored. Live API scheduling remains blocked until the connector is validated and enabled.
            </div>
          ) : (
            <button className="mt-4 btn btn-ai w-full justify-center" onClick={() => setOpenPostiz(true)}>
              Connect Postiz
            </button>
          )}
        </div>
      </div>

      <div className="card-flat overflow-hidden" data-testid="social-post-table">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <div>
            <div className="font-bold text-slate-900">Posts ready for social operations</div>
            <div className="text-xs text-slate-500">Approved content can be marked ready and prepared for Postiz.</div>
          </div>
          <button onClick={load} className="btn btn-outline !py-1.5 !px-3 text-xs">
            <RefreshCw className="w-3 h-3" /> Refresh
          </button>
        </div>
        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading posts...</div>
        ) : posts.length === 0 ? (
          <div className="p-10 text-center">
            <div className="font-bold text-slate-900">No saved posts yet</div>
            <p className="text-sm text-slate-500 mt-1">Generate and approve AI ideas first, then return here for scheduling preparation.</p>
            <Link to="/ai" className="btn btn-ai mt-4">Generate ideas</Link>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-widest text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="text-start p-4">Post</th>
                  <th className="text-start p-4">Context</th>
                  <th className="text-start p-4">Status</th>
                  <th className="text-start p-4">Postiz action</th>
                </tr>
              </thead>
              <tbody>
                {posts.map((post) => (
                  <tr key={post.id} className="border-b border-slate-50 align-top" data-testid={`social-post-${post.id}`}>
                    <td className="p-4 max-w-xl">
                      <div className="font-bold text-slate-900">{post.hook || "Untitled post"}</div>
                      <p className="text-xs text-slate-500 mt-1 line-clamp-2">{post.caption}</p>
                      <div className="flex flex-wrap gap-1 mt-2">
                        <span className="badge-pill badge-blue">{post.platform}</span>
                        <span className="badge-pill badge-slate">{post.format}</span>
                      </div>
                    </td>
                    <td className="p-4 text-xs text-slate-600">
                      <div className="font-semibold text-slate-900">{post.event_name || "No event"}</div>
                      <div>{post.campaign_name || "No campaign"}</div>
                    </td>
                    <td className="p-4">
                      <span className={`badge-pill ${statusBadge(post.status)}`}>{(post.status || "draft").replaceAll("_", " ")}</span>
                    </td>
                    <td className="p-4">
                      <button
                        className="btn btn-primary !py-1.5 !px-3 text-xs"
                        onClick={() => syncToPostiz(post)}
                        data-testid={`postiz-sync-${post.id}`}
                      >
                        <Send className="w-3 h-3" /> Sync to Postiz
                      </button>
                      <div className="mt-1 text-[11px] text-slate-500">
                        {postiz ? "Prepared locally. Live sync waits for connector enablement." : "Requires Postiz credential."}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Modal open={openPostiz} onClose={() => setOpenPostiz(false)} title="Postiz setup" testId="postiz-modal">
        <form onSubmit={savePostiz} className="space-y-3">
          <div>
            <label className="field-label">Postiz base URL</label>
            <input className="field-input mono" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          </div>
          <div>
            <label className="field-label">API key</label>
            <input required type="password" className="field-input mono" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </div>
          <div>
            <label className="field-label">Workspace or channel id (optional)</label>
            <input className="field-input mono" value={form.workspace_id} onChange={(e) => setForm({ ...form, workspace_id: e.target.value })} />
          </div>
          <div className="p-3 rounded-md bg-orange-50 border border-orange-200 text-xs text-orange-900">
            Saving this credential does not publish anything. Live scheduling remains blocked until connector validation is implemented and explicitly enabled.
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-outline" onClick={() => setOpenPostiz(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary">Save Postiz setup</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function SocialMetric({ label, value, tone = "orange" }) {
  const toneClass = tone === "green" ? "bg-green-500" : tone === "blue" ? "bg-blue-500" : tone === "slate" ? "bg-slate-500" : "bg-orange-500";
  return (
    <div className="p-3 rounded-lg bg-white border border-slate-200">
      <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold">{label}</div>
      <div className="text-2xl font-black text-slate-900 mt-1">{value}</div>
      <div className={`mt-2 h-1 w-8 rounded-full ${toneClass}`} />
    </div>
  );
}

function StatusBox({ label, value, ok }) {
  return (
    <div className="p-2 rounded-md bg-slate-50 border border-slate-100">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <span className={`badge-pill ${ok ? "badge-green" : "badge-orange"} mt-1 inline-block`}>
        {value}
      </span>
    </div>
  );
}
