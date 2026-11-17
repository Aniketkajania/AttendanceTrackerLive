import { useEffect, useState, useRef } from "react";
import { ImagePlus, Loader2, Camera, RefreshCw, X, Check, Trash2, Pencil } from "lucide-react";
import { api } from "../api";
import { Panel, inputCls, btnCls } from "../ui";

const SLOTS = [
  ["front", "Front face"],
  ["left", "Left side"],
  ["right", "Right side"],
  ["neutral", "Slight angle"],
];

export default function RegisterEmployee() {
  const [locs, setLocs] = useState([]);
  const [emps, setEmps] = useState([]);
  const [form, setForm] = useState({ employee_id: "", person_name: "", email: "", base_location: "" });
  const [files, setFiles] = useState({});
  const [busy, setBusy] = useState(false);
  const [faceChecks, setFaceChecks] = useState({});
  const [msg, setMsg] = useState(null);

  // Camera states
  const [showCamera, setShowCamera] = useState(false);
  const [activeSlotIdx, setActiveSlotIdx] = useState(0);
  const [camError, setCamError] = useState(null);

  const videoRef = useRef(null);
  const streamRef = useRef(null);

  const loadEmps = () => api("/api/employees").then(setEmps);

  useEffect(() => {
    api("/api/locations").then((l) => {
      setLocs(l);
      if (l.length > 0) setForm((f) => ({ ...f, base_location: l[0] }));
    });
    loadEmps();
  }, []);

  // Start webcam
  const startCamera = async () => {
    setCamError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
    } catch (err) {
      setCamError("Camera access denied or unavailable. Please check permissions.");
    }
  };

  // Stop webcam
  const stopCamera = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  };

  useEffect(() => {
    if (showCamera) {
      startCamera();
    } else {
      stopCamera();
    }
    return () => stopCamera();
  }, [showCamera]);

  // Capture frame from video feed
  const capturePhoto = () => {
    if (!videoRef.current) return;
    const video = videoRef.current;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;

    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const slotKey = SLOTS[activeSlotIdx][0];
        const file = new File([blob], `${slotKey}_${Date.now()}.jpg`, { type: "image/jpeg" });

        setFiles((prev) => ({ ...prev, [slotKey]: file }));
        setFaceChecks((prev) => ({ ...prev, [slotKey]: undefined }));

        // Auto-advance to next missing slot or next index
        if (activeSlotIdx < SLOTS.length - 1) {
          setActiveSlotIdx((idx) => idx + 1);
        } else {
          setShowCamera(false);
        }
      },
      "image/jpeg",
      0.92
    );
  };

  const openCamera = (index = 0) => {
    setActiveSlotIdx(index);
    setShowCamera(true);
  };

  const verifyPhotos = async () => {
    setBusy(true);
    setMsg(null);
    const outcomes = {};
    try {
      for (const [slot, label] of SLOTS) {
        if (!files[slot]) { outcomes[slot] = { usable: false, reason: "Missing photo" }; continue; }
        const fd = new FormData();
        fd.append("image", files[slot]);
        try { outcomes[slot] = await api("/api/face/detect", { method: "POST", body: fd }); }
        catch (err) { outcomes[slot] = { usable: false, reason: err.message }; }
      }
      setFaceChecks(outcomes);
      const usable = ["front", "neutral"].some(k => outcomes[k]?.usable);
      setMsg({ ok: usable, text: usable ? "Face detection completed. A usable frontal image is available for enrollment." : "No usable front/neutral face. Retake your photos before registration." });
      return usable;
    } finally { setBusy(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (SLOTS.some(([k]) => !files[k])) return setMsg({ ok: false, text: "Please add all 4 photos." });
    
    const valid = await verifyPhotos();
    if (!valid) return;
    const fd = new FormData();
    Object.entries(form).forEach(([k, v]) => fd.append(k, v));
    SLOTS.forEach(([k]) => fd.append(k, files[k]));
    
    setBusy(true);
    setMsg(null);
    try {
      const r = await api("/api/employees", { method: "POST", body: fd });
      setMsg({ ok: true, text: `Registered/Updated ${r.employee_id} using ${r.vectors_used} face vectors. ${r.warnings?.join(" ") || ""}` });
      setFiles({});
      setFaceChecks({});
      // Clear form after successful registration
      setForm({ employee_id: "", person_name: "", email: "", base_location: locs[0] || "" });
      loadEmps();
    } catch (err) {
      setMsg({ ok: false, text: err.message });
    }
    setBusy(false);
  };

  const handleEdit = (emp) => {
    setForm({
      employee_id: emp.employee_id,
      person_name: emp.person_name,
      email: emp.email,
      base_location: emp.base_location || locs[0] || "",
    });
    setFiles({});
    setFaceChecks({}); // Clear files so new photos are mandatory for re-registration
    setMsg({ ok: true, text: `Editing ${emp.employee_id}. Please take new photos and submit to update.` });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleDelete = async (empId) => {
    if (!window.confirm(`Are you sure you want to delete employee ${empId}? This will remove their attendance tracking data.`)) return;
    
    try {
      await api(`/api/employees/${empId}`, { method: "DELETE" });
      setMsg({ ok: true, text: `Employee ${empId} deleted successfully.` });
      loadEmps();
    } catch (err) {
      setMsg({ ok: false, text: `Failed to delete: ${err.message}` });
    }
  };

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-800">Register Employee</h1>
      
      <div className="grid gap-6 xl:grid-cols-5">
        <Panel className="xl:col-span-2">
          <form onSubmit={submit} className="space-y-3">
            <input
              required
              placeholder="Employee ID (e.g. GDL-A000709)"
              value={form.employee_id}
              onChange={set("employee_id")}
              className={inputCls}
              readOnly={!!emps.find(e => e.employee_id === form.employee_id)} // Prevent changing ID if editing
            />
            <input
              required
              placeholder="Full name"
              value={form.person_name}
              onChange={set("person_name")}
              className={inputCls}
            />
            <input
              required
              type="email"
              placeholder="Email"
              value={form.email}
              onChange={set("email")}
              className={inputCls}
            />
            <select value={form.base_location} onChange={set("base_location")} className={inputCls}>
              {locs.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>

            <button
              type="button"
              onClick={() => openCamera(0)}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-50 py-2.5 text-sm font-medium text-indigo-600 transition hover:bg-indigo-100"
            >
              <Camera size={18} /> Open Camera Sequence
            </button>

            <div className="grid grid-cols-2 gap-3">
              {SLOTS.map(([k, label], idx) => (
                <div key={k} className="relative aspect-square overflow-hidden rounded-xl border-2 border-dashed border-slate-300">
                  {files[k] ? (
                    <div className="group relative h-full w-full">
                      <img src={URL.createObjectURL(files[k])} alt={label} className="h-full w-full object-cover" />
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/50 opacity-0 transition group-hover:opacity-100">
                        <button
                          type="button"
                          onClick={() => openCamera(idx)}
                          className="flex items-center gap-1 rounded bg-white/90 px-2 py-1 text-xs font-semibold text-slate-800 hover:bg-white"
                        >
                          <Camera size={12} /> Retake
                        </button>
                      </div>
                    </div>
                  ) : (
                    <label className="flex h-full flex-col items-center justify-center cursor-pointer text-xs text-slate-500 hover:border-indigo-400">
                      <ImagePlus className="mb-1" />
                      <span>{label}</span>
                      <input
                        type="file"
                        accept="image/*"
                        hidden
                        onChange={(e) => { if (e.target.files?.[0]) { setFiles(v => ({ ...v, [k]: e.target.files[0] })); setFaceChecks(v => ({ ...v, [k]: undefined })); } }}
                      />
                    </label>
                  )}
                  {faceChecks[k] && <span className={`absolute right-1 top-1 rounded px-1 text-[10px] ${faceChecks[k].usable ? "bg-emerald-600 text-white" : "bg-amber-100 text-amber-900"}`} title={faceChecks[k].reason || "Face detected"}>{faceChecks[k].usable ? "Face OK" : "Retake"}</span>}
                  <span className="absolute bottom-1.5 left-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
                    {label}
                  </span>
                </div>
              ))}
            </div>

            <button type="button" disabled={busy} onClick={verifyPhotos} className="w-full rounded-xl border border-blue-200 bg-blue-50 py-2 text-sm font-semibold text-blue-700 disabled:opacity-50">Check Face Detection</button>
            <button disabled={busy} className={`${btnCls} w-full`}>
              {busy && <Loader2 className="animate-spin" size={16} />}
              Extract face vector & register
            </button>

            {msg && <p className={`text-sm ${msg.ok ? "text-emerald-600" : "text-rose-600"}`}>{msg.text}</p>}
          </form>
        </Panel>

        <Panel className="xl:col-span-3">
          <h2 className="mb-3 font-semibold text-slate-700">Enrolled employees ({emps.length})</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {emps.map((e) => (
              <div key={e.employee_id} className="flex items-center justify-between rounded-xl p-3 ring-1 ring-slate-200">
                <div className="flex items-center gap-3 overflow-hidden">
                  {e.photo_url ? (
                    <img src={e.photo_url} className="h-12 w-12 shrink-0 rounded-full object-cover" />
                  ) : (
                    <div className="h-12 w-12 shrink-0 rounded-full bg-slate-200" />
                  )}
                  <div className="min-w-0">
                    <div className="truncate font-medium">{e.person_name}</div>
                    <div className="truncate text-xs text-slate-500">
                      {e.employee_id} · {e.base_location}
                    </div>
                  </div>
                </div>
                
                {/* Action Buttons */}
                <div className="flex shrink-0 flex-col gap-1 ml-2">
                  <button 
                    onClick={() => handleEdit(e)}
                    title="Re-register User"
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-indigo-600 transition"
                  >
                    <Pencil size={16} />
                  </button>
                  <button 
                    onClick={() => handleDelete(e.employee_id)}
                    title="Delete User"
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-rose-600 transition"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {showCamera && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="relative w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-slate-800">
                  Step {activeSlotIdx + 1} of {SLOTS.length}: Position {SLOTS[activeSlotIdx][1]}
                </h3>
                <p className="text-xs text-slate-500">Align subject face cleanly in frame</p>
              </div>
              <button onClick={() => setShowCamera(false)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                <X size={20} />
              </button>
            </div>

            <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-slate-900">
              {camError ? (
                <div className="flex h-full items-center justify-center text-center text-xs text-rose-400 px-4">{camError}</div>
              ) : (
                <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-cover" />
              )}
            </div>

            <div className="mt-4 grid grid-cols-4 gap-2">
              {SLOTS.map(([k, label], idx) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setActiveSlotIdx(idx)}
                  className={`flex flex-col items-center rounded-lg p-1.5 text-[11px] border transition ${
                    activeSlotIdx === idx
                      ? "border-indigo-600 bg-indigo-50 text-indigo-700 font-medium"
                      : files[k]
                      ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                      : "border-slate-200 text-slate-500 hover:bg-slate-50"
                  }`}
                >
                  <span className="flex items-center gap-0.5">
                    {files[k] && <Check size={12} className="text-emerald-600" />}
                    {label}
                  </span>
                </button>
              ))}
            </div>

            <div className="mt-5 flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setShowCamera(false)}
                className="rounded-xl border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Close
              </button>

              <button
                type="button"
                onClick={capturePhoto}
                disabled={!!camError}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 py-2.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:opacity-50"
              >
                <Camera size={16} /> Snap {SLOTS[activeSlotIdx][1]}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}