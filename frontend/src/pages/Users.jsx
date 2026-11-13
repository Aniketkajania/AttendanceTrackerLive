import { useEffect, useState } from "react";
import { Trash2, Pencil } from "lucide-react";
import { api } from "../api";
import { Panel, inputCls, btnCls } from "../ui";

const EMPTY = { username: "", full_name: "", role: "viewer", password: "" };
const TONE = { admin: "bg-indigo-100 text-indigo-700", hr: "bg-amber-100 text-amber-700", viewer: "bg-slate-100 text-slate-600" };

export default function Users() {
  const [users, setUsers] = useState([]);
  const [f, setF] = useState(EMPTY);
  const [editing, setEditing] = useState(null);   // username being edited, or null
  const [msg, setMsg] = useState(null);

  const load = () => api("/api/users").then(setUsers).catch((e) => setMsg({ ok: false, text: e.message }));
  useEffect(() => { load(); }, []);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const reset = () => { setF(EMPTY); setEditing(null); };

  const save = async (e) => {
    e.preventDefault();
    try {
      await api(editing ? `/api/users/${editing}` : "/api/users", {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
      setMsg({ ok: true, text: editing ? `Updated ${editing}` : `Created ${f.username.toLowerCase()}` });
      reset(); load();
    } catch (err) { setMsg({ ok: false, text: err.message }); }
  };

  const remove = async (u) => {
    if (!confirm(`Delete login '${u.username}'? This cannot be undone.`)) return;
    try { await api(`/api/users/${u.username}`, { method: "DELETE" }); setMsg({ ok: true, text: `Deleted ${u.username}` }); load(); }
    catch (err) { setMsg({ ok: false, text: err.message }); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-800">User Access</h1>
      <div className="grid gap-6 xl:grid-cols-5">
        <Panel className="xl:col-span-2">
          <h2 className="mb-3 font-semibold text-slate-700">{editing ? `Edit ${editing}` : "Add a login"}</h2>
          <form onSubmit={save} className="space-y-3">
            <input required disabled={!!editing} placeholder="Username (e.g. priya.hr)" value={f.username} onChange={set("username")} className={`${inputCls} disabled:bg-slate-100`} />
            <input required placeholder="Full name" value={f.full_name} onChange={set("full_name")} className={inputCls} />
            <select value={f.role} onChange={set("role")} className={inputCls}>
              <option value="viewer">Viewer (view attendance and logs)</option>
              <option value="hr">HR (view + register employees)</option>
              <option value="admin">Admin (everything, incl. cameras and users)</option>
            </select>
            <input type="password" required={!editing} placeholder={editing ? "New password (blank = keep current)" : "Password (min 8 characters)"} value={f.password} onChange={set("password")} className={inputCls} />
            <div className="flex gap-2">
              <button className={`${btnCls} flex-1`}>{editing ? "Save changes" : "Create login"}</button>
              {editing && <button type="button" onClick={reset} className="rounded-lg bg-slate-100 px-4 text-sm">Cancel</button>}
            </div>
            {msg && <p className={`text-sm ${msg.ok ? "text-emerald-600" : "text-rose-600"}`}>{msg.text}</p>}
          </form>
        </Panel>
        <Panel className="overflow-x-auto p-0 xl:col-span-3">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="px-4 py-3">User</th><th className="px-4 py-3">Role</th><th className="px-4 py-3 text-right">Actions</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((u) => (
                <tr key={u.username} className="hover:bg-slate-50">
                  <td className="px-4 py-3"><div className="font-medium">{u.full_name}</div><div className="text-xs text-slate-400">{u.username}</div></td>
                  <td className="px-4 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase ${TONE[u.role]}`}>{u.role}</span></td>
                  <td className="px-4 py-3 text-right">
                    <button title="Edit / reset password" onClick={() => { setEditing(u.username); setF({ ...u, password: "" }); setMsg(null); }} className="mr-2 text-slate-500 hover:text-indigo-600"><Pencil size={16} /></button>
                    <button title="Delete" onClick={() => remove(u)} className="text-slate-500 hover:text-rose-600"><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}