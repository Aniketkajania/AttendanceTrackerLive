import { X, User } from "lucide-react";

export const inputCls =
  "w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-800 placeholder-slate-400 shadow-xs transition duration-150 focus:border-blue-600 focus:outline-none focus:ring-3 focus:ring-blue-500/15";

export const btnCls =
  "inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-xs transition-all duration-150 hover:bg-blue-500 hover:shadow-sm active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50";

export const btnSecondaryCls =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-xs transition-all hover:bg-slate-50 hover:text-slate-900 active:scale-[0.98]";

export function Kpi({ label, value, icon: Icon, tone, subtext }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-xs transition-all duration-200 hover:border-slate-300">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-bold tracking-wider text-slate-500 uppercase">{label}</p>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-slate-900 font-mono">
              {value ?? 0}
            </span>
            {subtext && <span className="text-xs font-medium text-slate-500">{subtext}</span>}
          </div>
        </div>
        <div className={`rounded-xl p-3 border ${tone}`}>
          <Icon size={22} strokeWidth={2.2} />
        </div>
      </div>
    </div>
  );
}

export function Badge({ status }) {
  const inside = status === "IN";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold tracking-wide ${
        inside
          ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/30"
          : "bg-slate-100 text-slate-600 ring-1 ring-slate-400/30"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          inside ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
        }`}
      />
      {inside ? "Inside Gate" : "Checked Out"}
    </span>
  );
}

export function Thumb({ src, onOpen, alt = "Biometric capture" }) {
  if (!src) {
    return (
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-slate-100 text-slate-400">
        <User size={18} />
      </div>
    );
  }
  return (
    <div className="group relative h-11 w-11 shrink-0 cursor-zoom-in overflow-hidden rounded-xl border border-slate-200 bg-slate-100 transition duration-150 hover:border-blue-500 hover:shadow-xs">
      <img
        src={src}
        alt={alt}
        onClick={() => onOpen(src)}
        loading="lazy"
        className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
      />
    </div>
  );
}

export function Lightbox({ src, onClose }) {
  if (!src) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in"
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white p-2 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full bg-slate-900/70 p-2 text-white hover:bg-slate-900 transition"
        >
          <X size={18} />
        </button>
        <img src={src} alt="Recognition capture" className="max-h-[80vh] w-auto rounded-xl object-contain" />
        <div className="px-3 py-2 text-center text-xs font-semibold text-slate-600">
          Gate Camera Audit Capture
        </div>
      </div>
    </div>
  );
}

export const Panel = ({ children, className = "" }) => (
  <div className={`rounded-2xl border border-slate-200 bg-white p-5 shadow-xs ${className}`}>
    {children}
  </div>
);