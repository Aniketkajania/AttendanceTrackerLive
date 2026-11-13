import { useEffect, useState, useRef } from "react";
import {
  Video,
  Plus,
  RefreshCw,
  CheckCircle2,
  Settings2,
  X,
  Loader2,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { api } from "../api";
import { Panel, inputCls, btnCls, btnSecondaryCls } from "../ui";

// WebRTC Player Component using MediaMTX WHEP
function WebRTCPlayer({ streamUrl }) {
  const videoRef = useRef(null);

  useEffect(() => {
    const pc = new RTCPeerConnection();
    
    // Tell the browser we only want to receive video
    pc.addTransceiver("video", { direction: "recvonly" });

    // When the stream connects, attach it to the video element
    pc.ontrack = (event) => {
      if (videoRef.current) {
        videoRef.current.srcObject = event.streams[0];
      }
    };

    // Standard WHEP (WebRTC HTTP Egress Protocol) connection flow
    pc.createOffer()
      .then((offer) => pc.setLocalDescription(offer))
      .then(() => {
        return fetch(streamUrl, {
          method: "POST",
          body: pc.localDescription.sdp,
          headers: { "Content-Type": "application/sdp" },
        });
      })
      .then((response) => response.text())
      .then((answer) => {
        pc.setRemoteDescription(
          new RTCSessionDescription({ type: "answer", sdp: answer })
        );
      })
      .catch(console.error);

    return () => {
      pc.close();
    };
  }, [streamUrl]);

  return (
    <video
      ref={videoRef}
      autoPlay
      muted
      playsInline
      className="max-h-full max-w-full object-contain pointer-events-none will-change-transform"
      onError={(e) => {
        e.target.style.display = "none";
        const fallback = e.target.parentElement.querySelector(".stream-fallback");
        if (fallback) fallback.style.display = "flex";
      }}
    />
  );
}

const EMPTY = {
  camera_id: "",
  camera_name: "",
  location: "",
  camera_role: "IN",
  connection_type: "RTSP",
  webcam_index: 0,
  ip_address: "",
  port: 554,
  username: "admin",
  password: "",
  rtsp_path: "/Streaming/Channels/101",
  is_active: true,
};

export default function Cameras() {
  const [cameras, setCameras] = useState([]);
  const [locs, setLocs] = useState([]);
  const [selectedLoc, setSelectedLoc] = useState("All");
  const [form, setForm] = useState(EMPTY);
  const [isEditing, setIsEditing] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [saving, setSaving] = useState(false);
  
  // Force HTTP stream reconnects on refresh
  const [streamKey, setStreamKey] = useState(Date.now());
  
  // Track which camera card is popped up in front
  const [expandedId, setExpandedId] = useState(null);

  const loadData = () => {
    setStreamKey(Date.now());
    api("/api/cameras")
      .then((data) => setCameras(data || []))
      .catch(console.error);
    api("/api/locations")
      .then((data) => setLocs(data || []))
      .catch(console.error);
  };

  useEffect(() => {
    loadData();
  }, []);

  // Escape key minimizes the card
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        setExpandedId(null);
        setShowModal(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const filteredCameras =
    selectedLoc === "All"
      ? cameras
      : cameras.filter((c) => c.location === selectedLoc);

  const handleEdit = (e, cam) => {
    e.stopPropagation();
    setForm({
      ...EMPTY,
      ...cam,
      is_active: Boolean(cam.is_active),
    });
    setIsEditing(true);
    setShowModal(true);
  };

  const handleCreateNew = () => {
    setForm({
      ...EMPTY,
      location: locs[0] || "",
    });
    setIsEditing(false);
    setShowModal(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api("/api/cameras", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      setShowModal(false);
      loadData();
    } catch (err) {
      alert(err.message || "Failed to save camera");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Background Dim Backdrop */}
      {expandedId && (
        <div
          className="fixed inset-0 z-40 bg-black/70 backdrop-blur-xs transition-opacity"
          onClick={() => setExpandedId(null)}
        />
      )}

      {/* Header Bar */}
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">
            Terminal Camera Wall & Stream Feeds
          </h1>
          <p className="text-[11px] text-slate-500">
            Click any camera card to expand it in front of the screen
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadData} className={btnSecondaryCls}>
            <RefreshCw size={13} /> Refresh Feeds
          </button>
          <button onClick={handleCreateNew} className={btnCls}>
            <Plus size={14} /> Add Gate Camera
          </button>
        </div>
      </div>

      {/* Location Filter Tabs */}
      <div className="flex items-center gap-1.5 overflow-x-auto border-b border-slate-200 pb-2 text-xs">
        <button
          onClick={() => setSelectedLoc("All")}
          className={`rounded-lg px-3 py-1.5 text-xs font-bold transition whitespace-nowrap ${
            selectedLoc === "All"
              ? "bg-blue-600 text-white shadow-2xs"
              : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
          }`}
        >
          All Locations ({cameras.length})
        </button>
        {locs.map((loc) => {
          const count = cameras.filter((c) => c.location === loc).length;
          return (
            <button
              key={loc}
              onClick={() => setSelectedLoc(loc)}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold transition whitespace-nowrap ${
                selectedLoc === loc
                  ? "bg-blue-600 text-white shadow-2xs"
                  : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {loc} ({count})
            </button>
          );
        })}
      </div>

      {/* Camera Grid Wall */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
        {filteredCameras.map((cam) => {
          const isLive = Boolean(cam.is_active);
          const isRTSP = cam.connection_type === "RTSP";
          const isExpanded = expandedId === cam.camera_id;

          return (
            <div
              key={cam.camera_id}
              onClick={() => {
                if (!isExpanded) setExpandedId(cam.camera_id);
              }}
              className={`group flex flex-col justify-between overflow-hidden rounded-xl border transition-all select-none ${
                isExpanded
                  ? "fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[90vw] max-w-2xl max-h-[75vh] shadow-2xl border-slate-700 bg-slate-900"
                  : "relative cursor-pointer border-slate-200 bg-white shadow-2xs hover:border-blue-400 hover:shadow-md"
              }`}
            >
              {/* Card Header */}
              <div
                className={`flex items-center justify-between border-b p-2.5 ${
                  isExpanded
                    ? "bg-slate-800 border-slate-700 text-white"
                    : "bg-slate-50/80 border-slate-100 text-slate-900 pointer-events-none"
                }`}
              >
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-bold leading-snug">
                      {cam.camera_name}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-bold ${
                        cam.camera_role === "IN"
                          ? "bg-emerald-100 text-emerald-800"
                          : "bg-rose-100 text-rose-800"
                      }`}
                    >
                      {cam.camera_role}
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-slate-400">
                    {cam.camera_id} • {cam.location}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 pointer-events-auto">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[9px] font-bold ${
                      isLive
                        ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20"
                        : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        isLive ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
                      }`}
                    />
                    {isLive ? (isExpanded ? "EXPANDED" : "ONLINE") : "STANDBY"}
                  </span>

                  {/* Settings Button */}
                  <button
                    onClick={(e) => handleEdit(e, cam)}
                    title="Configure Camera"
                    className={`rounded p-1 transition ${
                      isExpanded
                        ? "text-slate-400 hover:text-white hover:bg-slate-700"
                        : "text-slate-400 hover:bg-slate-200/70 hover:text-slate-700"
                    }`}
                  >
                    <Settings2 size={13} />
                  </button>

                  {/* Expand / Minimize Toggle */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedId(isExpanded ? null : cam.camera_id);
                    }}
                    title={isExpanded ? "Minimize" : "Expand"}
                    className={`rounded p-1 transition ${
                      isExpanded
                        ? "bg-red-600 text-white hover:bg-red-700"
                        : "text-slate-400 hover:text-blue-600"
                    }`}
                  >
                    {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={13} />}
                  </button>
                </div>
              </div>

              {/* Single Shared Video Frame */}
              <div
                className={`relative w-full bg-slate-950 flex items-center justify-center overflow-hidden [transform:translateZ(0)] ${
                  isExpanded ? "max-h-[50vh] aspect-video" : "aspect-video"
                }`}
              >
                {isLive ? (
                  <WebRTCPlayer 
                    key={`${cam.camera_id}-${streamKey}`}
                    streamUrl={`/api/cameras/${cam.camera_id}/whep`} 
                  />
                ) : null}

                {/* Standby / Offline Fallback */}
                <div
                  className={`stream-fallback flex-col items-center justify-center gap-1 text-slate-500 pointer-events-none ${
                    isLive ? "hidden" : "flex"
                  }`}
                >
                  <Video size={isExpanded ? 32 : 22} className="text-slate-600" />
                  <span className="text-[10px] font-mono tracking-tight text-slate-400">
                    {isLive ? "Connecting stream..." : "Camera Deactivated"}
                  </span>
                </div>

                {/* Hover prompt */}
                {!isExpanded && (
                  <div className="absolute inset-0 bg-slate-900/30 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
                    <span className="inline-flex items-center gap-1.5 bg-blue-600 text-white text-[11px] font-semibold px-2.5 py-1 rounded-md shadow">
                      <Maximize2 size={12} /> Click to expand
                    </span>
                  </div>
                )}

                {/* Overlay Tag */}
                <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/80 via-black/30 to-transparent px-2.5 py-1 text-[9px] font-mono text-white pointer-events-none">
                  <span className="truncate max-w-[200px]">
                    {isRTSP ? `rtsp://${cam.ip_address}:${cam.port}` : "USB Webcam (Local)"}
                  </span>
                  <span className="flex items-center gap-1 text-emerald-400 font-semibold">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    LIVE FEED
                  </span>
                </div>
              </div>

              {/* Card Footer Details */}
              <div
                className={`flex items-center justify-between border-t p-2 text-[10px] font-mono pointer-events-none ${
                  isExpanded
                    ? "bg-slate-800/90 border-slate-700 text-slate-300"
                    : "bg-white border-slate-100 text-slate-500"
                }`}
              >
                <span className="truncate max-w-[220px] text-slate-400">
                  {isRTSP ? cam.rtsp_path : `Device Index: ${cam.webcam_index}`}
                </span>
                <span className="flex items-center gap-1 font-semibold text-emerald-500">
                  <CheckCircle2 size={11} /> 512-D Vision
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {filteredCameras.length === 0 && (
        <Panel className="py-12 text-center text-slate-400">
          <p className="text-xs font-semibold text-slate-600">
            No cameras registered for: {selectedLoc}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-400">
            Click "Add Gate Camera" above to configure a stream.
          </p>
        </Panel>
      )}

      {/* Edit / Add Camera Form Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-sm font-bold text-slate-900">
                {isEditing ? `Edit Camera (${form.camera_id})` : "Register Gate Camera"}
              </h3>
              <button
                onClick={() => setShowModal(false)}
                className="rounded p-1 text-slate-400 hover:text-slate-700 transition"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Camera ID *
                  </label>
                  <input
                    required
                    disabled={isEditing}
                    value={form.camera_id}
                    onChange={(e) =>
                      setForm({ ...form, camera_id: e.target.value.toUpperCase().trim() })
                    }
                    placeholder="e.g. GHH_IN_01"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Camera Name *
                  </label>
                  <input
                    required
                    value={form.camera_name}
                    onChange={(e) => setForm({ ...form, camera_name: e.target.value })}
                    placeholder="e.g. Main Gate Entry"
                    className={inputCls}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Facility Location *
                  </label>
                  <select
                    value={form.location}
                    onChange={(e) => setForm({ ...form, location: e.target.value })}
                    className={inputCls}
                  >
                    {locs.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Gate Role *
                  </label>
                  <select
                    value={form.camera_role}
                    onChange={(e) => setForm({ ...form, camera_role: e.target.value })}
                    className={inputCls}
                  >
                    <option value="IN">IN (Entry Gate)</option>
                    <option value="OUT">OUT (Exit Gate)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Connection Type
                  </label>
                  <select
                    value={form.connection_type}
                    onChange={(e) => setForm({ ...form, connection_type: e.target.value })}
                    className={inputCls}
                  >
                    <option value="RTSP">RTSP Stream (IP CCTV)</option>
                    <option value="WEBCAM">USB / Local Webcam</option>
                  </select>
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Camera Status
                  </label>
                  <div className="flex items-center gap-2 pt-1.5">
                    <input
                      type="checkbox"
                      id="is_active_toggle"
                      checked={form.is_active}
                      onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                    <label htmlFor="is_active_toggle" className="text-xs text-slate-700 font-medium">
                      Enable Live Stream
                    </label>
                  </div>
                </div>
              </div>

              {form.connection_type === "RTSP" ? (
                <>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="col-span-2">
                      <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                        IP Address *
                      </label>
                      <input
                        required
                        value={form.ip_address || ""}
                        onChange={(e) => setForm({ ...form, ip_address: e.target.value.trim() })}
                        placeholder="192.168.101.50"
                        className={inputCls}
                      />
                    </div>
                    <div>
                      <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                        Port *
                      </label>
                      <input
                        type="number"
                        required
                        value={form.port || 554}
                        onChange={(e) => setForm({ ...form, port: parseInt(e.target.value) || 554 })}
                        className={inputCls}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                        RTSP Username
                      </label>
                      <input
                        value={form.username || ""}
                        onChange={(e) => setForm({ ...form, username: e.target.value })}
                        placeholder="admin"
                        className={inputCls}
                      />
                    </div>
                    <div>
                      <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                        RTSP Password
                      </label>
                      <input
                        type="password"
                        value={form.password || ""}
                        onChange={(e) => setForm({ ...form, password: e.target.value })}
                        placeholder="••••••••"
                        className={inputCls}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      RTSP Channel Path *
                    </label>
                    <input
                      required
                      value={form.rtsp_path || ""}
                      onChange={(e) => setForm({ ...form, rtsp_path: e.target.value.trim() })}
                      placeholder="/Streaming/Channels/101"
                      className={inputCls}
                    />
                  </div>
                </>
              ) : (
                <div>
                  <label className="mb-0.5 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Webcam Device Index
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={form.webcam_index || 0}
                    onChange={(e) =>
                      setForm({ ...form, webcam_index: parseInt(e.target.value) || 0 })
                    }
                    className={inputCls}
                  />
                </div>
              )}

              <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className={btnSecondaryCls}
                >
                  Cancel
                </button>
                <button type="submit" disabled={saving} className={btnCls}>
                  {saving && <Loader2 className="animate-spin" size={13} />}
                  <span>{isEditing ? "Save Changes" : "Register Camera"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}