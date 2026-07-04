import React from "react";

/** Simple modal wrapper — used across the app for create/edit dialogs. */
export default function Modal({ open, onClose, title, children, testId = "modal" }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/45 backdrop-blur-sm p-4"
      onClick={onClose}
      data-testid={`${testId}-backdrop`}
    >
      <div
        className="bg-white border border-slate-200 rounded-xl w-full max-w-lg overflow-hidden rise-in"
        onClick={(e) => e.stopPropagation()}
        data-testid={testId}
      >
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="text-lg font-bold tracking-tight text-slate-900">{title}</h3>
          <button
            onClick={onClose}
            className="btn btn-ghost !p-1"
            data-testid={`${testId}-close`}
          >
            ✕
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}
