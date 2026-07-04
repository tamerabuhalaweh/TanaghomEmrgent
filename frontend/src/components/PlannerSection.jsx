import React, { useEffect, useState, useCallback } from "react";
import PlannerCard from "./PlannerCard";
import { api } from "../lib/api";
import { CalendarClock, FileText, Mail, MessageCircle, Zap, Wallet, EyeOff, ClipboardCheck } from "lucide-react";

const APPROVAL = ["draft", "pending_review", "approved", "changes_requested"];

const CONFIG = {
  contentRequirements: {
    title: "Content Requirements",
    resource: "content-requirements",
    testIdKey: "content",
    emptyCta: "No content requirements yet — add reels, videos, or landing pages needed for the campaign.",
    statusField: "status",
    defaultForm: { title: "", asset_type: "reel", platform: "instagram", description: "", due_date: "", owner_role: "content", status: "planned", notes: "" },
    fields: [
      { name: "title", label: "Title", required: true, wide: true },
      { name: "asset_type", label: "Asset type", type: "select", options: ["video","image","carousel","reel","story","landing_page","email_copy","whatsapp_copy","other"] },
      { name: "platform", label: "Platform", type: "select", options: ["instagram","meta","youtube","whatsapp","email","landing_page","other"] },
      { name: "due_date", label: "Due date", type: "date" },
      { name: "owner_role", label: "Owner role" },
      { name: "status", label: "Status", type: "select", options: ["planned","in_progress","pending_review","approved","blocked","done"] },
      { name: "description", label: "Description", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "title", label: "Title" },
      { name: "asset_type", label: "Type" },
      { name: "platform", label: "Platform" },
      { name: "due_date", label: "Due" },
    ],
  },
  emailPlans: {
    title: "Email Campaign Plan",
    resource: "email-plans",
    testIdKey: "email",
    emptyCta: "No email sequences planned yet — add nurture, reminder or upsell campaigns.",
    statusField: "approval_status",
    defaultForm: { sequence_name: "", audience_segment: "warm+cold", email_count: 3, subject_draft: "", body_draft: "", goal: "nurture", approval_status: "draft", status: "planned" },
    fields: [
      { name: "sequence_name", label: "Sequence name", required: true, wide: true },
      { name: "audience_segment", label: "Audience segment" },
      { name: "email_count", label: "Email count", type: "number" },
      { name: "goal", label: "Goal", type: "select", options: ["awareness","nurture","upsell","reminder","last_chance","post_event"] },
      { name: "approval_status", label: "Approval", type: "select", options: APPROVAL },
      { name: "subject_draft", label: "Subject draft", wide: true },
      { name: "body_draft", label: "Body draft", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "sequence_name", label: "Sequence" },
      { name: "goal", label: "Goal" },
      { name: "email_count", label: "Emails" },
      { name: "audience_segment", label: "Audience" },
    ],
  },
  whatsappPlans: {
    title: "WhatsApp Follow-Up Plan",
    resource: "whatsapp-plans",
    testIdKey: "whatsapp",
    emptyCta: "No WhatsApp plan yet — add reminders, sales follow-ups or urgency messages.",
    statusField: "approval_status",
    defaultForm: { audience_segment: "warm", frequency: "1/week", content_type: "text", message_draft: "", goal: "reminder", approval_status: "draft", status: "planned" },
    fields: [
      { name: "audience_segment", label: "Audience segment", required: true },
      { name: "frequency", label: "Frequency" },
      { name: "content_type", label: "Content type", type: "select", options: ["text","image","video","link","mixed"] },
      { name: "goal", label: "Goal", type: "select", options: ["reminder","nurture","sales_follow_up","urgency","post_event"] },
      { name: "approval_status", label: "Approval", type: "select", options: APPROVAL },
      { name: "message_draft", label: "Message draft", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "audience_segment", label: "Audience" },
      { name: "goal", label: "Goal" },
      { name: "content_type", label: "Type" },
      { name: "frequency", label: "Frequency" },
    ],
  },
  upsellPlans: {
    title: "Upsell / FOMO Plan",
    resource: "upsell-plans",
    testIdKey: "upsell",
    emptyCta: "No upsell offers planned — add FOMO-driven offers for warm/hot leads.",
    statusField: "approval_status",
    defaultForm: { target_segment: "past-buyers", offer: "", fomo_angle: "", planned_channel: "email", expected_outcome: "", approval_status: "draft", status: "planned" },
    fields: [
      { name: "target_segment", label: "Target segment", required: true },
      { name: "offer", label: "Offer", required: true, wide: true },
      { name: "fomo_angle", label: "FOMO angle" },
      { name: "planned_channel", label: "Channel", type: "select", options: ["email","whatsapp","sales_call","ghl_workflow","mixed"] },
      { name: "approval_status", label: "Approval", type: "select", options: APPROVAL },
      { name: "expected_outcome", label: "Expected outcome", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "target_segment", label: "Segment" },
      { name: "offer", label: "Offer" },
      { name: "planned_channel", label: "Channel" },
    ],
  },
  budgetPlans: {
    title: "Budget Plan",
    resource: "budget-plans",
    testIdKey: "budget",
    emptyCta: "No budget planned by channel yet.",
    defaultForm: { channel: "meta", planned_budget: 0, expected_leads: 0, expected_purchases: 0, expected_revenue: 0, notes: "" },
    fields: [
      { name: "channel", label: "Channel", type: "select", options: ["meta","instagram","youtube","whatsapp","email","organic","dark_ad","referral","other"] },
      { name: "planned_budget", label: "Planned budget ($)", type: "number" },
      { name: "expected_leads", label: "Expected leads", type: "number" },
      { name: "expected_purchases", label: "Expected purchases", type: "number" },
      { name: "expected_revenue", label: "Expected revenue ($)", type: "number" },
      { name: "notes", label: "Notes", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "channel", label: "Channel" },
      { name: "planned_budget", label: "Planned $", render: (r) => `$${Number(r.planned_budget || 0).toLocaleString()}` },
      { name: "expected_leads", label: "Exp. leads" },
      { name: "expected_revenue", label: "Exp. rev $", render: (r) => `$${Number(r.expected_revenue || 0).toLocaleString()}` },
    ],
  },
  darkAdPlans: {
    title: "Dark Ads Plan",
    resource: "dark-ad-plans",
    testIdKey: "darkad",
    emptyCta: "No dark ads planned — add off-page ads to run via Meta Ads Manager.",
    statusField: "status",
    defaultForm: { campaign_name: "", audience_definition: "", platform: "meta", creative_format: "video", objective: "leads", planned_budget: 0, status: "planned", notes: "" },
    fields: [
      { name: "campaign_name", label: "Campaign name", required: true, wide: true },
      { name: "platform", label: "Platform", type: "select", options: ["meta","instagram","youtube","other"] },
      { name: "creative_format", label: "Creative", type: "select", options: ["video","image","carousel","reel","story","other"] },
      { name: "objective", label: "Objective", type: "select", options: ["leads","conversions","awareness","retargeting"] },
      { name: "planned_budget", label: "Planned budget ($)", type: "number" },
      { name: "status", label: "Status", type: "select", options: ["planned","active","paused","completed","blocked"] },
      { name: "audience_definition", label: "Audience", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "campaign_name", label: "Campaign" },
      { name: "platform", label: "Platform" },
      { name: "objective", label: "Objective" },
      { name: "planned_budget", label: "Planned $", render: (r) => `$${Number(r.planned_budget || 0).toLocaleString()}` },
    ],
  },
  salesTasks: {
    title: "Sales Follow-Up Tasks",
    resource: "sales-tasks",
    testIdKey: "salestask",
    emptyCta: "No sales tasks yet — add calls, follow-ups or payment nudges.",
    statusField: "status",
    defaultForm: { title: "", task_type: "call", owner_role: "sales", related_lead_id: "", due_date: "", status: "open", notes: "" },
    fields: [
      { name: "title", label: "Title", required: true, wide: true },
      { name: "task_type", label: "Type", type: "select", options: ["call","whatsapp_reply","meeting_follow_up","no_show_follow_up","payment_follow_up","lead_review","other"] },
      { name: "owner_role", label: "Owner role" },
      { name: "due_date", label: "Due date", type: "date" },
      { name: "status", label: "Status", type: "select", options: ["open","in_progress","done","blocked"] },
      { name: "related_lead_id", label: "Related lead id (optional)" },
      { name: "notes", label: "Next action", type: "textarea", wide: true },
    ],
    listCols: [
      { name: "title", label: "Title" },
      { name: "task_type", label: "Type" },
      { name: "owner_role", label: "Owner" },
      { name: "due_date", label: "Due" },
    ],
  },
};

function BudgetSummary({ eventId }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    (async () => {
      const { data } = await api.get(`/events/${eventId}/planner/summary`);
      setRows(data.budget_by_channel || []);
    })();
  }, [eventId]);
  if (rows.length === 0) return null;
  return (
    <div className="card-flat p-5" data-testid="planner-budget-summary">
      <h3 className="text-base font-bold tracking-tight text-slate-900 mb-3">
        Planned vs Actual by Channel
      </h3>
      <div className="space-y-2">
        {rows.map((b) => {
          const total = Math.max(b.planned || 1, b.actual || 1);
          const pctPlan = Math.min(100, ((b.planned || 0) / total) * 100);
          const pctActual = Math.min(100, ((b.actual || 0) / total) * 100);
          const positive = (b.variance || 0) >= 0;
          return (
            <div key={b.channel} className="text-xs" data-testid={`planner-budget-row-${b.channel}`}>
              <div className="flex justify-between mb-1">
                <span className="font-semibold text-slate-900">{b.channel}</span>
                <span className={positive ? "text-green-700" : "text-red-700"}>
                  variance ${Number(b.variance).toLocaleString()}
                </span>
              </div>
              <div className="flex gap-1 mb-1">
                <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-slate-900" style={{ width: `${pctPlan}%` }} />
                </div>
                <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-orange-500" style={{ width: `${pctActual}%` }} />
                </div>
              </div>
              <div className="flex justify-between text-slate-500 mono">
                <span>Planned ${Number(b.planned).toLocaleString()}</span>
                <span>Actual ${Number(b.actual).toLocaleString()}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function PlannerSection({ eventId }) {
  return (
    <div className="space-y-6" data-testid="planner-section">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="w-4 h-4 text-orange-600" />
        <h2 className="text-lg font-bold tracking-tight text-slate-900">Execution Plan</h2>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PlannerCard eventId={eventId} {...CONFIG.contentRequirements} />
        <PlannerCard eventId={eventId} {...CONFIG.emailPlans} />
        <PlannerCard eventId={eventId} {...CONFIG.whatsappPlans} />
        <PlannerCard eventId={eventId} {...CONFIG.upsellPlans} />
        <PlannerCard eventId={eventId} {...CONFIG.budgetPlans} />
        <PlannerCard eventId={eventId} {...CONFIG.darkAdPlans} />
      </div>
      <BudgetSummary eventId={eventId} />
      <PlannerCard eventId={eventId} {...CONFIG.salesTasks} />
    </div>
  );
}
