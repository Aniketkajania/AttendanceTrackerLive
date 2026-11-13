import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Panel, Kpi, inputCls, btnCls, btnSecondaryCls } from "../ui";
import { Users, UserCheck, UserX, ContactRound, CalendarDays, Plus, RefreshCcw } from "lucide-react";

const today = () => new Date().toLocaleDateString("en-CA");
const headings = {
  overview: ["Attendance Analytics", "Live daily staff, visitor and leave statistics"],
  reports: ["Daily Attendance Report", "Shift-aware roster, leave status and downloadable CSV"],
  visitors: ["Visitor Management", "Register arrivals and record departures"],
  shifts: ["Shift Management", "Manage work shifts and employee assignments"],
  leaves: ["Leave Management", "Submit and review staff leave requests"],
  areas: ["Area Selection", "Define monitored zones for your office locations"],
};
const schemas = {
  visitors: [
    ["full_name", "Visitor name", "text", true],
    ["organization", "Organization"],
    ["host_employee_id", "Host employee ID"],
    ["purpose", "Purpose of visit"],
    ["location", "Location", "text", true],
  ],
  shifts: [
    ["shift_name", "Shift name", "text", true],
    ["start_time", "Start time", "time", true],
    ["end_time", "End time", "time", true],
    ["grace_minutes", "Grace period (minutes)", "number"],
  ],
  leaves: [
    ["employee_id", "Employee ID", "text", true],
    ["start_date", "From", "date", true],
    ["end_date", "To", "date", true],
    ["leave_type", "Leave type", "select", true, ["CASUAL", "SICK", "EARNED", "UNPAID", "OTHER"]],
    ["reason", "Reason"],
  ],
  areas: [
    ["name", "Area name", "text", true],
    ["location", "Location", "text", true],
    ["description", "Description"],
  ],
};
const initial = {
  visitors: { full_name: "", organization: "", host_employee_id: "", purpose: "", location: "" },
  shifts: { shift_name: "", start_time: "09:00", end_time: "18:00", grace_minutes: 15 },
  leaves: { employee_id: "", start_date: today(), end_date: today(), leave_type: "CASUAL", reason: "" },
  areas: { name: "", location: "", description: "" },
};
const columns = {
  visitors: [["full_name", "Visitor"], ["organization", "Organization"], ["location", "Location"], ["checked_in_at", "Arrived"], ["checked_out_at", "Departed"]],
  shifts: [["shift_name", "Shift"], ["start_time", "Start"], ["end_time", "End"], ["grace_minutes", "Grace (min)"]],
  leaves: [["person_name", "Employee"], ["leave_type", "Type"], ["start_date", "From"], ["end_date", "To"], ["status", "Status"]],
  areas: [["name", "Area"], ["location", "Location"], ["description", "Description"]],
};
const titleCase = s => String(s || "").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());

export default function Operations({ mode }) {
  const [date, setDate] = useState(today());
  const [rows, setRows] = useState([]);
  const [overview, setOverview] = useState(null);
  const [form, setForm] = useState(initial[mode] || {});
  const [assignment, setAssignment] = useState({ employee_id: "", shift_id: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [role, setRole] = useState("viewer");
  const [shifts, setShifts] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [cameraAreas, setCameraAreas] = useState([]);
  const [cameraAssignment, setCameraAssignment] = useState({ camera_id:"",area_id:"" });
  const [report, setReport] = useState(null);
  const [reportLocation, setReportLocation] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      const data = mode === "overview"
        ? await api(`/api/operations/overview?work_date=${date}`)
        : mode === "reports"
        ? await api(`/api/operations/reports/daily?work_date=${date}${reportLocation ? `&location=${encodeURIComponent(reportLocation)}` : ""}`)
        : await api(`/api/operations/${mode}`);
      if (mode === "overview") setOverview(data);
      else if (mode === "reports") setReport(data);
      else setRows(data);
      if (mode === "areas") {
        setCameraAreas(await api("/api/operations/camera-areas"));
      }
      if (mode === "shifts") {
        const [a, me] = await Promise.all([api("/api/operations/assignments"), api("/api/auth/me")]);
        setAssignments(a);
        setRole(me.role);
      } else {
        const me = await api("/api/auth/me");
        setRole(me.role);
      }
    } catch (e) {
      setError(e.message || "Could not load data. Apply the SQL migration first.");
    }
  }, [mode, date, reportLocation]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (mode === "shifts") setShifts(rows); }, [mode, rows]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const payload = { ...form };
      if (mode === "visitors" && !payload.host_employee_id) payload.host_employee_id = null;
      await api(`/api/operations/${mode}`, { method: "POST", body: JSON.stringify(payload) });
      setForm(initial[mode]); setShowCreate(false);
      await load();
    } catch (e) { setError(e.message || "Unable to save"); }
    finally { setBusy(false); }
  };

  const act = async (url, payload) => {
    setBusy(true); setError("");
    try {
      await api(url, { method: "POST", body: JSON.stringify(payload || {}) });
      await load();
    } catch (e) { setError(e.message || "Action failed"); }
    finally { setBusy(false); }
  };

  const canCreate = role === "admin" || (role === "hr" && (mode === "leaves" || mode === "visitors"));
  const [heading, subtitle] = headings[mode] || ["Operations", ""];

  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-slate-900">{heading}</h1>
        <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
      </div>
      <div className="flex gap-2">
        <button className={btnSecondaryCls} onClick={load} disabled={busy}><RefreshCcw size={16} /> Refresh</button>
        {canCreate && mode !== "overview" && <button className={btnCls} onClick={() => setShowCreate(!showCreate)}><Plus size={16} /> Add {mode === "leaves" ? "Request" : mode.slice(0, -1)}</button>}
      </div>
    </div>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}
    {mode === "overview" ? <>
      <Panel>
        <label className="mb-2 block text-xs font-bold text-slate-500">Reporting Date</label>
        <input type="date" value={date} className={inputCls+" max-w-xs"} onChange={e => setDate(e.target.value)} />
      </Panel>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi label="Active Staff" value={overview?.staff} icon={Users} tone="bg-blue-50 text-blue-700 border-blue-200" />
        <Kpi label="Present" value={overview?.present} icon={UserCheck} tone="bg-emerald-50 text-emerald-700 border-emerald-200" />
        <Kpi label="Absent Estimate" value={overview?.absent_estimate} icon={UserX} tone="bg-rose-50 text-rose-700 border-rose-200" />
        <Kpi label="Visitors" value={overview?.visitors} icon={ContactRound} tone="bg-indigo-50 text-indigo-700 border-indigo-200" />
      </div>
      <Panel><div className="flex items-center gap-3"><CalendarDays className="text-blue-600" /><div><p className="font-semibold text-slate-800">Approved leave</p><p className="text-sm text-slate-500">{overview?.on_leave ?? "—"} employees on leave on the selected date</p></div></div></Panel>
      <p className="text-xs text-slate-500">Absent count is an estimate based on attendance records and approved leave. Shift schedules, holidays, and incomplete punches can affect this figure.</p>
    </> : mode === "reports" ? <>
      <Panel>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs font-semibold text-slate-600">Reporting Date
            <input type="date" className={inputCls+" mt-1"} value={date} onChange={e=>setDate(e.target.value)} />
          </label>
          <label className="text-xs font-semibold text-slate-600">Location (exact)
            <input className={inputCls+" mt-1"} value={reportLocation} placeholder="All locations" onChange={e=>setReportLocation(e.target.value)} />
          </label>
          <a className={btnSecondaryCls} href={`/api/operations/reports/daily.csv?work_date=${date}${reportLocation ? `&location=${encodeURIComponent(reportLocation)}` : ""}`}>Export CSV</a>
        </div>
      </Panel>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Staff" value={report?.summary?.staff} icon={Users}/>
        <Kpi label="Present" value={report?.summary?.present} icon={UserCheck}/>
        <Kpi label="Late" value={report?.summary?.late} icon={Clock3}/>
        <Kpi label="On leave" value={report?.summary?.on_leave} icon={CalendarDays}/>
      </div>
      <Panel className="overflow-x-auto">
        <table className="min-w-[900px] w-full text-sm text-left">
          <thead><tr className="border-b text-xs text-slate-500">{["Employee","Location","Shift","First IN","Last OUT","Attendance assessment"].map(x=><th key={x} className="px-3 py-3">{x}</th>)}</tr></thead>
          <tbody>{(report?.rows||[]).map(r=><tr key={r.employee_id} className="border-b border-slate-100">
            <td className="px-3 py-3">{r.person_name}<div className="text-xs text-slate-400">{r.employee_id}</div></td>
            <td className="px-3 py-3">{r.base_location}</td>
            <td className="px-3 py-3">{r.shift_name||"Unassigned"}<div className="text-xs text-slate-400">{r.shift_start||""}</div></td>
            <td className="px-3 py-3">{r.first_check_in||"—"}</td>
            <td className="px-3 py-3">{r.last_check_out||"—"}</td>
            <td className="px-3 py-3 font-semibold text-slate-700">{r.attendance_status?.replaceAll("_"," ")}</td>
          </tr>)}</tbody>
        </table>
        {(report?.rows||[]).length===0 && <p className="py-8 text-center text-sm text-slate-500">No employee records found.</p>}
      </Panel>
      <p className="text-xs text-slate-500">Late status uses the assigned day shift and grace period. Overnight shifts, unassigned schedules and missing punches require HR review. This report is not a payroll determination.</p>
    </> : <>
      {showCreate && canCreate && <Panel>
        <h2 className="mb-4 text-lg font-bold text-slate-900">New {titleCase(mode.slice(0, -1))}</h2>
        <form onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {(schemas[mode] || []).map(([key, label, type = "text", required, options]) =>
            <label key={key} className="text-xs font-semibold text-slate-600">
              <span className="mb-1 block">{label}</span>
              {type === "select" ? <select required={required} className={inputCls} value={form[key] ?? ""} onChange={e => setForm(v => ({ ...v, [key]: e.target.value }))}>
                {options.map(x => <option key={x} value={x}>{titleCase(x)}</option>)}
              </select> : <input className={inputCls} type={type} required={!!required} value={form[key] ?? ""} onChange={e => setForm(v => ({ ...v, [key]: type === "number" ? Number(e.target.value) : e.target.value }))} />}
            </label>)}
          <div className="flex items-end"><button className={btnCls} disabled={busy} type="submit">Save</button></div>
        </form>
      </Panel>}
      {mode === "shifts" && role !== "viewer" && <Panel>
        <h2 className="mb-4 text-base font-bold text-slate-800">Assign Employee to Shift</h2>
        <form className="flex flex-wrap items-end gap-3" onSubmit={e => {e.preventDefault();act("/api/operations/assignments", { ...assignment, shift_id: Number(assignment.shift_id) });}}>
          <label className="min-w-48 flex-1 text-xs font-semibold text-slate-600">Employee ID<input required className={inputCls+" mt-1"} value={assignment.employee_id} onChange={e => setAssignment(v => ({...v, employee_id: e.target.value}))}/></label>
          <label className="min-w-48 flex-1 text-xs font-semibold text-slate-600">Shift<select required className={inputCls+" mt-1"} value={assignment.shift_id} onChange={e => setAssignment(v => ({...v, shift_id: e.target.value}))}><option value="">Select shift</option>{shifts.map(s => <option key={s.id} value={s.id}>{s.shift_name}</option>)}</select></label>
          <button className={btnCls} disabled={busy}>Assign</button>
        </form>
        {assignments.length > 0 && <p className="mt-3 text-xs text-slate-500">{assignments.length} employee assignments configured</p>}
      </Panel>}
      {mode === "areas" && <Panel>
        <h2 className="mb-3 font-bold text-slate-800">Camera Area Mapping</h2>
        <p className="mb-4 text-xs text-slate-500">Assign existing cameras to an area. This records administrative configuration; it does not automatically change recognition behavior.</p>
        {role==="admin" && <form className="mb-4 flex flex-wrap items-end gap-3" onSubmit={e=>{e.preventDefault(); act("/api/operations/camera-areas",{camera_id:cameraAssignment.camera_id,area_id:Number(cameraAssignment.area_id)});}}>
          <label className="text-xs font-semibold text-slate-600">Camera
            <select className={inputCls+" mt-1"} value={cameraAssignment.camera_id} required onChange={e=>setCameraAssignment(v=>({...v,camera_id:e.target.value}))}>
              <option value="">Choose camera</option>
              {cameraAreas.map(c=><option key={c.camera_id} value={c.camera_id}>{c.camera_name} ({c.camera_id})</option>)}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-600">Area
            <select className={inputCls+" mt-1"} value={cameraAssignment.area_id} required onChange={e=>setCameraAssignment(v=>({...v,area_id:e.target.value}))}>
              <option value="">Choose area</option>
              {rows.map(a=><option key={a.id} value={a.id}>{a.location}: {a.name}</option>)}
            </select>
          </label>
          <button className={btnCls} disabled={busy}>Assign Camera</button>
        </form>}
        <div className="space-y-1">{cameraAreas.map(c=><div key={c.camera_id} className="flex justify-between gap-2 border-b border-slate-100 py-2 text-sm"><span>{c.camera_name} <span className="text-slate-400">({c.location})</span></span><span className="font-semibold">{c.area_name||"Unassigned"}</span></div>)}</div>
      </Panel>}
      <Panel className="overflow-x-auto">
        <table className="w-full min-w-[650px] text-left text-sm">
          <thead><tr className="border-b border-slate-200 text-[11px] font-bold uppercase tracking-wide text-slate-500">
            {(columns[mode] || []).map(([key,label]) => <th key={key} className="px-3 py-3">{label}</th>)}
            {(mode === "leaves" || mode === "visitors") && <th className="px-3 py-3">Actions</th>}
          </tr></thead>
          <tbody>{rows.map(r => <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50">
            {(columns[mode] || []).map(([key]) => <td key={key} className="px-3 py-3 text-slate-700">{r[key] == null ? "—" : String(r[key])}</td>)}
            {mode === "leaves" && <td className="px-3 py-3">
              {r.status === "PENDING" && role !== "viewer" && <div className="flex gap-2">
                <button disabled={busy} className="text-xs font-bold text-emerald-700" onClick={() => act(`/api/operations/leaves/${r.id}/review`, {status:"APPROVED"})}>Approve</button>
                <button disabled={busy} className="text-xs font-bold text-rose-700" onClick={() => act(`/api/operations/leaves/${r.id}/review`, {status:"REJECTED"})}>Reject</button>
              </div>}
            </td>}
            {mode === "visitors" && <td className="px-3 py-3">
              {!r.checked_out_at && role !== "viewer" && <button disabled={busy} className="text-xs font-bold text-blue-700" onClick={() => act(`/api/operations/visitors/${r.id}/checkout`)}>Check out</button>}
            </td>}
          </tr>)}</tbody>
        </table>
        {rows.length === 0 && <p className="py-10 text-center text-sm text-slate-500">No records found.</p>}
      </Panel>
    </>}
  </div>;
}
