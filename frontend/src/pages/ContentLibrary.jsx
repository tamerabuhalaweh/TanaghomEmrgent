import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { PageHeader, SectionTitle } from "../components/ui-bits";
import Modal from "../components/Modal";
import { api } from "../lib/api";
import { Check, Edit3, Filter, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";

const ALL = "all";
const STATUSES = [ALL, "draft", "approved", "ready_for_scheduling", "rejected"];
const PLATFORMS = [ALL, "meta", "instagram", "youtube", "tiktok", "whatsapp", "email"];

function statusBadge(status) {
  if (status === "approved") return "badge-green";
  if (status === "ready_for_scheduling") return "badge-blue";
  if (status === "rejected") return "badge-red";
  return "badge-slate";
}

function statusLabel(status) {
  return (status || "draft").replaceAll("_", " ");
}

const EMPTY_EDIT = {
  id: "",
  hook: "",
  caption: "",
  cta: "",
  hashtags: "",
  status: "draft",
  scheduled_at: "",
};

export default function ContentLibrary() {
  const [params, setParams] = useSearchParams();
  const [events, setEvents] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState(EMPTY_EDIT);
  const [filters, setFilters] = useState({
    event: params.get("event") || ALL,
    campaign: params.get("campaign") || ALL,
    platform: params.get("platform") || ALL,
    status: params.get("status") || ALL,
  });

  const loadEvents = async () => {
    const { data } = await api.get("/events");
    setEvents(data || []);
  };

  const loadCampaigns = async (eventId) => {
    if (!eventId || eventId === ALL) {
      setCampaigns([]);
      return;
    }
    const { data } = await api.get(`/events/${eventId}/campaigns`);
    setCampaigns(data || []);
  };

  const loadPosts = async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams();
      if (filters.event !== ALL) query.set("event_id", filters.event);
      if (filters.campaign !== ALL) query.set("campaign_id", filters.campaign);
      if (filters.platform !== ALL) query.set("platform", filters.platform);
      if (filters.status !== ALL) query.set("status", filters.status);
      const { data } = await api.get(`/posts${query.toString() ? `?${query.toString()}` : ""}`);
      setPosts(data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not load saved content");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadEvents(); }, []);
  useEffect(() => { loadCampaigns(filters.event); }, [filters.event]);
  useEffect(() => {
    const next = new URLSearchParams();
    if (filters.event !== ALL) next.set("event", filters.event);
    if (filters.campaign !== ALL) next.set("campaign", filters.campaign);
    if (filters.platform !== ALL) next.set("platform", filters.platform);
    if (filters.status !== ALL) next.set("status", filters.status);
    setParams(next, { replace: true });
    loadPosts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const counts = useMemo(() => ({
    total: posts.length,
    approved: posts.filter((p) => p.status === "approved").length,
    ready: posts.filter((p) => p.status === "ready_for_scheduling").length,
    draft: posts.filter((p) => !p.status || p.status === "draft").length,
  }), [posts]);

  const setFilter = (key, value) => {
    setFilters((current) => ({
      ...current,
      [key]: value,
      ...(key === "event" ? { campaign: ALL } : {}),
    }));
  };

  const openEdit = (post) => {
    setEditForm({
      id: post.id,
      hook: post.hook || "",
      caption: post.caption || "",
      cta: post.cta || "",
      hashtags: (post.hashtags || []).join(" "),
      status: post.status || "draft",
      scheduled_at: post.scheduled_at || "",
    });
    setEditOpen(true);
  };

  const patchPost = async (id, body, success = "Updated") => {
    try {
      await api.patch(`/posts/${id}`, body);
      toast.success(success);
      await loadPosts();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Update failed");
    }
  };

  const saveEdit = async (e) => {
    e.preventDefault();
    await patchPost(editForm.id, {
      hook: editForm.hook,
      caption: editForm.caption,
      cta: editForm.cta,
      hashtags: editForm.hashtags.split(/\s+/).filter(Boolean),
      status: editForm.status,
      scheduled_at: editForm.scheduled_at || null,
    }, "Content updated");
    setEditOpen(false);
  };

  const deletePost = async (post) => {
    if (!window.confirm("Delete this saved post?")) return;
    try {
      await api.delete(`/posts/${post.id}`);
      toast.success("Deleted");
      await loadPosts();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto" data-testid="content-library-page">
      <PageHeader
        title="Content Library"
        subtitle="Every approved AI idea is saved here as reusable campaign content. Edit it, approve it, and prepare it for scheduling without hunting through campaigns."
        actions={<Link to="/ai" className="btn btn-ai"><Send className="w-4 h-4" /> Generate More Ideas</Link>}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Metric label="Saved posts" value={counts.total} />
        <Metric label="Approved" value={counts.approved} tone="green" />
        <Metric label="Ready for scheduling" value={counts.ready} tone="blue" />
        <Metric label="Drafts" value={counts.draft} tone="slate" />
      </div>

      <div className="card-flat p-4 mb-6" data-testid="content-filters">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-orange-500" />
          <SectionTitle>Find Content</SectionTitle>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Select label="Event" value={filters.event} onChange={(v) => setFilter("event", v)}>
            <option value={ALL}>All events</option>
            {events.map((event) => <option key={event.id} value={event.id}>{event.name}</option>)}
          </Select>
          <Select label="Campaign" value={filters.campaign} onChange={(v) => setFilter("campaign", v)}>
            <option value={ALL}>All campaigns</option>
            {campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}
          </Select>
          <Select label="Platform" value={filters.platform} onChange={(v) => setFilter("platform", v)}>
            {PLATFORMS.map((platform) => <option key={platform} value={platform}>{platform === ALL ? "All platforms" : platform}</option>)}
          </Select>
          <Select label="Status" value={filters.status} onChange={(v) => setFilter("status", v)}>
            {STATUSES.map((status) => <option key={status} value={status}>{status === ALL ? "All statuses" : statusLabel(status)}</option>)}
          </Select>
        </div>
      </div>

      {loading ? (
        <div className="card-flat p-10 text-center text-sm text-slate-500">Loading saved content...</div>
      ) : posts.length === 0 ? (
        <div className="card-flat p-10 text-center" data-testid="content-empty">
          <div className="text-lg font-bold text-slate-900">No saved content yet</div>
          <p className="text-sm text-slate-500 mt-1">Generate AI ideas, approve the best ones, and they will appear here.</p>
          <Link to="/ai" className="btn btn-ai mt-4">Generate first idea</Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {posts.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              onEdit={() => openEdit(post)}
              onApprove={() => patchPost(post.id, { status: "approved" }, "Approved")}
              onReady={() => patchPost(post.id, { status: "ready_for_scheduling" }, "Marked ready for scheduling")}
              onDelete={() => deletePost(post)}
            />
          ))}
        </div>
      )}

      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit saved content" testId="content-edit-modal">
        <form onSubmit={saveEdit} className="space-y-3">
          <div>
            <label className="field-label">Hook</label>
            <input className="field-input" value={editForm.hook} onChange={(e) => setEditForm({ ...editForm, hook: e.target.value })} />
          </div>
          <div>
            <label className="field-label">Caption</label>
            <textarea className="field-input min-h-[120px]" value={editForm.caption} onChange={(e) => setEditForm({ ...editForm, caption: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label">CTA</label>
              <input className="field-input" value={editForm.cta} onChange={(e) => setEditForm({ ...editForm, cta: e.target.value })} />
            </div>
            <div>
              <label className="field-label">Status</label>
              <select className="field-input" value={editForm.status} onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}>
                {STATUSES.filter((s) => s !== ALL).map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="field-label">Hashtags</label>
            <input className="field-input mono text-xs" value={editForm.hashtags} onChange={(e) => setEditForm({ ...editForm, hashtags: e.target.value })} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn btn-outline" onClick={() => setEditOpen(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary">Save changes</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function Metric({ label, value, tone = "orange" }) {
  const toneClass = tone === "green" ? "bg-green-500" : tone === "blue" ? "bg-blue-500" : tone === "slate" ? "bg-slate-500" : "bg-orange-500";
  return (
    <div className="card-flat p-4">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value mt-2">{value}</div>
      <div className={`mt-3 h-1 w-10 rounded-full ${toneClass}`} />
    </div>
  );
}

function Select({ label, value, onChange, children }) {
  return (
    <div>
      <label className="field-label">{label}</label>
      <select className="field-input" value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
    </div>
  );
}

function PostCard({ post, onEdit, onApprove, onReady, onDelete }) {
  return (
    <div className="card-flat p-5" data-testid={`content-post-${post.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1 mb-2">
            <span className="badge-pill badge-blue">{post.platform}</span>
            <span className="badge-pill badge-slate">{post.format}</span>
            <span className={`badge-pill ${statusBadge(post.status)}`}>{statusLabel(post.status)}</span>
          </div>
          <h3 className="text-lg font-black text-slate-900 leading-tight">{post.hook || "Untitled post"}</h3>
          <div className="text-xs text-slate-500 mt-1">
            {post.event_name || "No event"} / {post.campaign_name || "No campaign"}
          </div>
        </div>
        <button className="btn btn-outline !p-2" onClick={onEdit} title="Edit"><Edit3 className="w-4 h-4" /></button>
      </div>
      <p className="mt-4 text-sm text-slate-700 whitespace-pre-line line-clamp-5">{post.caption}</p>
      {post.cta && <div className="mt-3 text-sm font-semibold text-slate-900">CTA: {post.cta}</div>}
      {post.hashtags?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {post.hashtags.map((tag) => <span key={tag} className="text-xs text-blue-700">{tag}</span>)}
        </div>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {post.status !== "approved" && <button className="btn btn-primary !py-1.5 !px-3 text-xs" onClick={onApprove}><Check className="w-3 h-3" /> Approve</button>}
        {post.status !== "ready_for_scheduling" && <button className="btn btn-ai !py-1.5 !px-3 text-xs" onClick={onReady}><Send className="w-3 h-3" /> Ready for scheduling</button>}
        <button className="btn btn-danger !py-1.5 !px-3 text-xs" onClick={onDelete}><Trash2 className="w-3 h-3" /> Delete</button>
      </div>
    </div>
  );
}
