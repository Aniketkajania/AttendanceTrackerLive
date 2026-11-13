import { useEffect, useState } from "react";
import { api } from "../api";
import { Thumb, Lightbox, Panel, inputCls } from "../ui";

export default function AuditLogs() {
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState([]);
  const [zoom, setZoom] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => api(`/api/logs?search=${encodeURIComponent(search)}`).then(setRows), 250);
    return () => clearTimeout(t);
  }, [search]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-800">Gate Audit Logs</h1>
      <Panel><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by employee ID or name" className={inputCls} /></Panel>
      <Panel className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>{["Photo", "Employee", "Event", "Time", "Location", "Camera", "Match"].map((h) => <th key={h} className="px-4 py-3">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r) => (
              <tr key={r.log_id} className="hover:bg-slate-50">
                <td className="px-4 py-2"><Thumb src={r.snapshot_url} onOpen={setZoom} /></td>
                <td className="px-4 py-2"><div className="font-medium">{r.person_name}</div><div className="text-xs text-slate-400">{r.employee_id}</div></td>
                <td className="px-4 py-2"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${r.event_type === "IN" ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>{r.event_type}</span></td>
                <td className="px-4 py-2">{r.event_timestamp}</td>
                <td className="px-4 py-2">{r.camera_location}</td>
                <td className="px-4 py-2 text-slate-500">{r.camera_id}</td>
                <td className="px-4 py-2">{Number(r.confidence_score).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Lightbox src={zoom} onClose={() => setZoom(null)} />
    </div>
  );
}
