import { useState } from "react";
import { ShieldCheck, Loader2, Video, Database, CheckCircle2 } from "lucide-react";
import { api } from "../api";
import { inputCls, btnCls } from "../ui";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      onLogin(data);
    } catch (e2) {
      setErr(e2.message || "Invalid corporate credentials");
    }
    setBusy(false);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-100/70">
      {/* Left Column: Brand Showcase */}
      <div className="relative hidden h-full w-1/2 flex-col justify-between border-r border-slate-200 bg-white p-8 xl:p-10 lg:flex">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#f1f5f9_1px,transparent_1px),linear-gradient(to_bottom,#f1f5f9_1px,transparent_1px)] bg-[size:24px_24px] opacity-75 pointer-events-none" />

        {/* Top: Logo */}
        <div className="relative z-10">
          <div className="inline-flex items-center rounded-xl border border-slate-200 bg-white p-2.5 shadow-xs">
            <img
              src="/gateway-logo.png"
              alt="Gateway Distriparks"
              className="h-8 w-auto object-contain"
              onError={(e) => {
                e.target.style.display = "none";
                e.target.parentNode.innerHTML =
                  '<div class="px-2 font-extrabold tracking-tight text-slate-900 text-sm">GATEWAY DISTRIPARKS</div>';
              }}
            />
          </div>
          <p className="mt-2 text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            Inland Container Depots & Rail Logistics
          </p>
        </div>

        {/* Center: Highlights */}
        <div className="relative z-10 max-w-md space-y-3.5 my-auto">
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50/80 px-2.5 py-0.5 text-[11px] font-semibold text-blue-700">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-600 animate-pulse" />
            Biometric Gate Security Portal
          </div>
          <h2 className="text-2xl font-extrabold tracking-tight text-slate-900 leading-snug">
            HQ & Terminal Personnel Attendance System
          </h2>
          <p className="text-xs text-slate-600 leading-relaxed">
            Real-time biometric recognition engine synchronizing gate entry, check-out audits, and inter-terminal roaming across operational facilities.
          </p>

          <div className="grid grid-cols-1 gap-2 pt-1">
            {[
              { icon: Video, title: "RTSP Vision Pipelines", desc: "Automated CCTV capture without manual card punching" },
              { icon: ShieldCheck, title: "512-D Face Verification", desc: "Anti-spoofing periocular verification" },
              { icon: Database, title: "Automated Audit Logs", desc: "Exportable compliance time-stamping & work hours" },
            ].map((item, idx) => (
              <div key={idx} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-2.5">
                <div className="rounded-lg bg-blue-100 p-1.5 text-blue-700">
                  <item.icon size={15} />
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-800">{item.title}</div>
                  <div className="text-[11px] text-slate-500">{item.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom: Meta */}
        <div className="relative z-10 flex items-center justify-between border-t border-slate-200 pt-3 text-[11px] text-slate-500">
          <span>VisionTrack Engine v2.4</span>
          <span className="flex items-center gap-1.5 font-medium text-emerald-700">
            <CheckCircle2 size={13} /> Systems Operational
          </span>
        </div>
      </div>

      {/* Right Column: Centered Form */}
      <div className="flex h-full flex-1 items-center justify-center p-6 sm:p-8">
        <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-lg">
          <div className="mb-4 flex flex-col items-center lg:hidden">
            <img
              src="/gateway-logo.png"
              alt="Gateway Distriparks"
              className="h-8 w-auto object-contain"
              onError={(e) => {
                e.target.style.display = "none";
                e.target.parentNode.innerHTML =
                  '<div class="font-extrabold tracking-tight text-slate-900 text-base">GATEWAY DISTRIPARKS</div>';
              }}
            />
          </div>

          <div className="mb-5">
            <h1 className="text-xl font-bold tracking-tight text-slate-900">Sign In</h1>
            <p className="mt-1 text-xs text-slate-500">
              Access the terminal with your admin or HR credentials
            </p>
          </div>

          {err && (
            <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700">
              {err}
            </div>
          )}

          <form onSubmit={submit} className="space-y-3.5">
            <div>
              <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-600">
                Username
              </label>
              <input
                autoFocus
                required
                placeholder="Enter user or admin ID"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-600">
                Password
              </label>
              <input
                required
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </div>

            <button disabled={busy} className={`${btnCls} w-full py-2.5 text-sm font-semibold`}>
              {busy ? <Loader2 className="animate-spin" size={16} /> : <ShieldCheck size={17} />}
              <span>{busy ? "Validating..." : "Sign In to Portal"}</span>
            </button>
          </form>

          <div className="mt-6 border-t border-slate-100 pt-3 text-center text-[10px] text-slate-400">
            Gateway Distriparks Limited • Internal Security
          </div>
        </div>
      </div>
    </div>
  );
}