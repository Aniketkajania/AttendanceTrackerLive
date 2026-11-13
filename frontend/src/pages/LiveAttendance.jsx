import { useEffect, useState } from "react";
import { Download, Users, LogIn, LogOut, Route, RefreshCw } from "lucide-react";
import { api } from "../api";
import { Kpi, Badge, Thumb, Lightbox, Panel, inputCls, btnCls } from "../ui";

const today = () => new Date().toLocaleDateString("en-CA");
const time = (t) => (t ? t.slice(11, 19) : "—");
const hrs = (n) => Number(n || 0).toFixed(2);

export default function LiveAttendance() {
  const [date, setDate] = useState(today());
  const [location, setLocation] = useState("All Locations");
  const [search, setSearch] = useState("");
  const [locs, setLocs] = useState([]);
  const [data, setData] = useState({ stats: {}, rows: [] });
  const [zoom, setZoom] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const qs = new URLSearchParams({ date, location, search }).toString();
  const load = () => {
    setIsRefreshing(true);
    api(`/api/attendance?${qs}`)
      .then(setData)
      .catch(console.error)
      .finally(() => setTimeout(() => setIsRefreshing(false), 350));
  };

  useEffect(() => {
    api("/api/locations").then(setLocs);
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 250);
    const i = setInterval(load, 15000);
    return () => {
      clearTimeout(t);
      clearInterval(i);
    };
  }, [qs]);

  const { stats, rows } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">Live Daily Attendance</h1>
          <p className="text-xs text-slate-500">Real-time gate pass and biometric camera detection records</p>
        </div>
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 shadow-xs">
          <RefreshCw size={13} className={isRefreshing ? "animate-spin text-blue-600" : "text-slate-400"} />
          <span>Auto-syncs 15s</span>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi
          label="Total Present"
          value={stats.total_present}
          icon={Users}
          tone="bg-blue-50 text-blue-700 border-blue-200"
          subtext="Headcount"
        />
        <Kpi
          label="Currently In"
          value={stats.currently_in}
          icon={LogIn}
          tone="bg-emerald-50 text-emerald-700 border-emerald-200"
          subtext="On-premises"
        />
        <Kpi
          label="Checked Out"
          value={stats.checked_out}
          icon={LogOut}
          tone="bg-rose-50 text-rose-700 border-rose-200"
          subtext="Left gate"
        />
        <Kpi
          label="Roaming"
          value={stats.roaming}
          icon={Route}
          tone="bg-amber-50 text-amber-700 border-amber-200"
          subtext="Inter-site"
        />
      </div>

      {/* Filter Toolbar */}
      <Panel className="!p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="w-full sm:w-auto">
            <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Date
            </label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={`${inputCls} !py-2 !text-xs font-semibold`}
            />
          </div>

          <div className="w-full sm:w-52">
            <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Location
            </label>
            <select
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className={`${inputCls} !py-2 !text-xs font-semibold`}
            >
              <option>All Locations</option>
              {locs.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </div>

          <div className="min-w-[240px] flex-1">
            <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Search Personnel
            </label>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by Employee ID or Name..."
              className={`${inputCls} !py-2 !text-xs`}
            />
          </div>

          <div className="self-end pt-1">
            <a className={`${btnCls} !py-2 !text-xs`} href={`/api/attendance/export?${qs}`}>
              <Download size={14} /> Export Excel
            </a>
          </div>
        </div>
      </Panel>

      {/* Data Table */}
      <Panel className="overflow-hidden !p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-5 py-3.5">Employee</th>
                <th className="px-4 py-3.5">Status</th>
                <th className="px-4 py-3.5">First Entry</th>
                <th className="px-4 py-3.5">Last Exit</th>
                <th className="px-4 py-3.5">Work Time</th>
                <th className="px-4 py-3.5">Away Time</th>
                <th className="px-4 py-3.5">Checks</th>
                <th className="px-5 py-3.5">Locations</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-14 text-center text-slate-400">
                    <p className="font-semibold text-slate-500">No attendance activity recorded for this criteria.</p>
                    <p className="mt-1 text-xs text-slate-400">Try adjusting your filters or date selection.</p>
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <tr key={r.id} className="transition-colors hover:bg-slate-50">
                    <td className="px-5 py-3.5">
                      <div className="font-semibold text-slate-900">{r.person_name}</div>
                      <div className="text-xs font-mono text-slate-500">{r.employee_id}</div>
                    </td>
                    <td className="px-4 py-3.5">
                      <Badge status={r.current_status} />
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3">
                        <Thumb src={r.first_check_in_image_url} onOpen={setZoom} />
                        <div>
                          <div className="font-bold text-slate-800 font-mono text-xs">{time(r.first_check_in)}</div>
                          <div className="text-[11px] text-slate-500">{r.first_check_in_location || "—"}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-3">
                        <Thumb src={r.last_check_out_image_url} onOpen={setZoom} />
                        <div>
                          <div className="font-bold text-slate-800 font-mono text-xs">
                            {r.last_check_out ? time(r.last_check_out) : "Active"}
                          </div>
                          <div className="text-[11px] text-slate-500">{r.last_check_out_location || "—"}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="inline-flex rounded-lg bg-emerald-50 px-2 py-0.5 font-mono text-xs font-bold text-emerald-700">
                        {hrs(r.total_working_hours)}h
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="inline-flex rounded-lg bg-amber-50 px-2 py-0.5 font-mono text-xs font-bold text-amber-700">
                        {hrs(r.out_of_office_hours)}h
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">
                        {r.total_checks}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-xs text-slate-500">
                      {r.visited_locations || "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Lightbox src={zoom} onClose={() => setZoom(null)} />
    </div>
  );
}