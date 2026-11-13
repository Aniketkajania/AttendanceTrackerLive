import { useEffect, useState } from "react";
import {
  CalendarCheck,
  ScrollText,
  UserPlus,
  Camera,
  LogOut,
  UserCog,
  ChevronRight,
} from "lucide-react";
import { api } from "./api";
import Login from "./pages/Login";
import LiveAttendance from "./pages/LiveAttendance";
import AuditLogs from "./pages/AuditLogs";
import RegisterEmployee from "./pages/RegisterEmployee";
import Cameras from "./pages/Cameras";
import Users from "./pages/Users";
import Operations from "./pages/Operations";
import { ClipboardList, Clock3, MapPinned, ContactRound, BarChart3 } from "lucide-react";

// Sign the user out after this many minutes with no mouse / keyboard / touch activity. 0 = never.
const IDLE_MINUTES = 15;

const ALL = ["admin", "hr", "viewer"];
const NAV = [
  { id: "live", label: "Live Attendance", icon: CalendarCheck, page: LiveAttendance, roles: ALL },
  { id: "logs", label: "Gate Audit Logs", icon: ScrollText, page: AuditLogs, roles: ALL },
  { id: "enroll", label: "Register Face", icon: UserPlus, page: RegisterEmployee, roles: ["admin", "hr"] },
  { id: "cams", label: "Cameras & RTSP", icon: Camera, page: Cameras, roles: ["admin"] },
  { id: "users", label: "User Access", icon: UserCog, page: Users, roles: ["admin"] },
  { id: "overview", label: "Analytics", icon: BarChart3, page: () => <Operations mode="overview" />, roles: ALL },
  { id: "reports", label: "Daily Reports", icon: ScrollText, page: () => <Operations mode="reports" />, roles: ALL },
  { id: "visitors", label: "Visitors", icon: ContactRound, page: () => <Operations mode="visitors" />, roles: ["admin", "hr"] },
  { id: "shifts", label: "Shift Management", icon: Clock3, page: () => <Operations mode="shifts" />, roles: ALL },
  { id: "leaves", label: "Leave Management", icon: ClipboardList, page: () => <Operations mode="leaves" />, roles: ["admin", "hr"] },
  { id: "areas", label: "Area Selection", icon: MapPinned, page: () => <Operations mode="areas" />, roles: ALL },
];

export default function App() {
  const [user, setUser] = useState(undefined);
  const [active, setActive] = useState("live");

  useEffect(() => {
    const timeout = setTimeout(() => {
      setUser((prev) => (prev === undefined ? null : prev));
    }, 2000);

    api("/api/auth/me")
      .then((res) => {
        clearTimeout(timeout);
        setUser(res);
      })
      .catch(() => {
        clearTimeout(timeout);
        setUser(null);
      });

    const expired = () => setUser(null);
    window.addEventListener("auth-expired", expired);
    return () => {
      clearTimeout(timeout);
      window.removeEventListener("auth-expired", expired);
    };
  }, []);

  // Idle timeout. The Live Attendance page refreshes itself every 15 s, so "no requests" can never mean "idle";
  // we watch real user input instead.
  useEffect(() => {
    if (!user || !IDLE_MINUTES) return;
    let last = Date.now();
    const touch = () => { last = Date.now(); };
    const events = ["mousemove", "mousedown", "keydown", "scroll", "touchstart"];
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const check = setInterval(() => {
      if (Date.now() - last > IDLE_MINUTES * 60 * 1000) {
        api("/api/auth/logout", { method: "POST" }).catch(() => {});
        setUser(null);
      }
    }, 15000);
    return () => {
      clearInterval(check);
      events.forEach((e) => window.removeEventListener(e, touch));
    };
  }, [user]);

  if (user === undefined) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-700">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          <p className="text-xs font-semibold tracking-wider uppercase text-slate-500">Connecting to terminal...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Login onLogin={(u) => { setUser(u); setActive("live"); }} />;
  }

  const nav = NAV.filter((n) => n.roles && n.roles.includes(user?.role || "viewer"));
  const activeItem = nav.find((n) => n.id === active) || nav[0] || NAV[0];
  const Page = activeItem?.page || LiveAttendance;

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
  };

  const userInitials = (user?.username || "AD").slice(0, 2).toUpperCase();

  return (
    <div className="flex min-h-screen bg-slate-100/70 text-slate-800">
      {/* Light Corporate Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col border-r border-slate-200 bg-white p-5 md:flex shadow-xs">
        
        {/* Gateway Distriparks Brand Logo Container */}
        <div className="mb-6 rounded-xl border border-slate-200 bg-white p-3 shadow-xs">
          <img
            src="/gateway-logo.png"
            alt="Gateway Distriparks"
            className="h-8 w-auto max-w-full object-contain mx-auto"
            onError={(e) => {
              e.target.style.display = "none";
              e.target.parentNode.innerHTML =
                '<div class="text-center font-extrabold tracking-tight text-slate-900 text-sm">GATEWAY DISTRIPARKS</div>';
            }}
          />
        </div>

        {/* Portal Status Tag */}
        <div className="mb-6 flex items-center justify-between border-b border-slate-100 pb-4">
          <div className="text-[11px] font-bold tracking-wider text-slate-400 uppercase">
            Attendance Portal
          </div>
          <div className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-emerald-600/20">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-600 animate-pulse" />
            LIVE
          </div>
        </div>

        {/* Navigation Items */}
        <div className="mb-2 text-[11px] font-bold tracking-wider text-slate-400 uppercase">
          Menu
        </div>

        <nav className="space-y-1">
          {nav.map(({ id, label, icon: Icon }) => {
            const isCurrent = active === id;
            return (
              <button
                key={id}
                onClick={() => setActive(id)}
                className={`group flex w-full items-center justify-between rounded-xl px-3.5 py-2.5 text-left text-sm font-semibold transition duration-150 ${
                  isCurrent
                    ? "bg-blue-600 text-white shadow-sm shadow-blue-500/25"
                    : "text-slate-600 hover:bg-slate-100/80 hover:text-slate-900"
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon
                    size={18}
                    className={`transition ${isCurrent ? "text-white" : "text-slate-500 group-hover:text-slate-700"}`}
                  />
                  <span>{label}</span>
                </div>
                {isCurrent && <ChevronRight size={15} className="text-white/80" />}
              </button>
            );
          })}
        </nav>

        {/* User Card */}
        <div className="mt-auto rounded-xl border border-slate-200 bg-slate-50/80 p-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-xs font-bold text-white shadow-xs">
              {userInitials}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-bold text-slate-800">{user?.full_name || user?.username}</div>
              <div className="text-[11px] font-semibold text-blue-600 uppercase">{user?.role}</div>
            </div>
            <button
              onClick={logout}
              title="Sign out"
              className="rounded-lg p-1.5 text-slate-400 hover:bg-white hover:text-rose-600 hover:shadow-xs transition"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="min-w-0 flex-1 p-5 md:p-8">
        <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3.5 shadow-xs md:hidden">
          <div className="flex items-center justify-between">
            <img src="/gateway-logo.png" alt="Gateway Distriparks" className="h-7 w-auto object-contain" />
            <button onClick={logout} className="flex items-center gap-1.5 text-xs font-bold text-rose-600">
              <LogOut size={14} /> Exit
            </button>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {nav.map((n) => (
              <button
                key={n.id}
                onClick={() => setActive(n.id)}
                className={`whitespace-nowrap rounded-xl px-3.5 py-2 text-xs font-bold transition ${
                  active === n.id ? "bg-blue-600 text-white shadow-xs" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                }`}
              >
                {n.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mx-auto max-w-7xl">
          <Page />
        </div>
      </main>
    </div>
  );
}