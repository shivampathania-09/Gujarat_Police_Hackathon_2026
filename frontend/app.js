/**
 * Gujarat Police Surveillance - Frontend Command Center
 * Real-Time Leaflet.js Mapping, WebSocket Alerts, and ANPR Analytics
 */

// Application Configuration
const CONFIG = {
  API_BASE: "http://localhost:8000/api",
  WS_URL: "ws://localhost:8000/ws",
  GUJARAT_CENTER: [22.2587, 71.1924],
  DEFAULT_ZOOM: 7,
  RECONNECT_INTERVAL: 3000,
  MAX_FEED_ITEMS: 50
};

// Application State
const state = {
  map: null,
  cameraMarkers: new Map(), // camera_id -> { marker, radarLayer, data }
  totalDetections: 0,
  watchlistHits: 0,
  activeCamerasCount: 0,
  ws: null,
  audioContext: null,
  soundEnabled: true,
  currentAlertTimeout: null,
  routeLayerGroup: null,
  activeTrackedPlate: null
};

// Fallback Mock Cameras in case backend is offline
const FALLBACK_CAMERAS = [
  { id: "CAM_AHM_SG_01", location_name: "SG Highway - ISKCON Cross Road", latitude: 23.0305, longitude: 72.5074, district: "Ahmedabad" },
  { id: "CAM_SUR_ATH_02", location_name: "Athwa Gate Junction", latitude: 21.1834, longitude: 72.8105, district: "Surat" },
  { id: "CAM_VAD_ALK_03", location_name: "Alkapuri Circle", latitude: 22.3106, longitude: 73.1812, district: "Vadodara" },
  { id: "CAM_RAJ_TRI_04", location_name: "Trikon Baug Chowk", latitude: 22.3008, longitude: 70.8022, district: "Rajkot" },
  { id: "CAM_GND_INF_05", location_name: "Infocity Crossroad, CH-0", latitude: 23.2156, longitude: 72.6369, district: "Gandhinagar" }
];


// ==========================================
// Web Audio Synthesizer (Zero External Dependencies)
// ==========================================

function getAudioContext() {
  if (!state.audioContext) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) state.audioContext = new AudioCtx();
  }
  if (state.audioContext && state.audioContext.state === "suspended") {
    state.audioContext.resume();
  }
  return state.audioContext;
}

function playSonarBlip() {
  if (!state.soundEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(950, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1400, ctx.currentTime + 0.08);
    gain.gain.setValueAtTime(0.04, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.08);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.09);
  } catch (e) {
    console.debug("Audio play suppressed:", e);
  }
}

function playEmergencySiren() {
  if (!state.soundEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const now = ctx.currentTime;
    
    // High-low alternating police alarm siren
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(800, now);
    osc.frequency.linearRampToValueAtTime(1100, now + 0.25);
    osc.frequency.linearRampToValueAtTime(800, now + 0.5);
    osc.frequency.linearRampToValueAtTime(1100, now + 0.75);
    osc.frequency.linearRampToValueAtTime(800, now + 1.0);

    gain.gain.setValueAtTime(0.15, now);
    gain.gain.linearRampToValueAtTime(0.18, now + 0.5);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 1.2);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 1.25);
  } catch (e) {
    console.debug("Emergency audio error:", e);
  }
}


// ==========================================
// Leaflet Map Custom Icons & Markers
// ==========================================

function createTacticalCameraIcon(isAlert = false) {
  const color = isAlert ? "#ef4444" : "#06b6d4";
  const glow = isAlert ? "rgba(239, 68, 68, 0.8)" : "rgba(6, 182, 212, 0.6)";

  const html = `
    <div style="position: relative; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center;">
      ${isAlert ? '<div class="radar-ring"></div>' : ''}
      <div style="
        width: 28px;
        height: 28px;
        background: #0f172a;
        border: 2px solid ${color};
        box-shadow: 0 0 12px ${glow};
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: ${color};
        transition: all 0.3s ease;
      ">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
          <circle cx="12" cy="13" r="3"/>
        </svg>
      </div>
    </div>
  `;

  return L.divIcon({
    html: html,
    className: 'tactical-camera-icon',
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -18]
  });
}

function initMap() {
  state.map = L.map('surveillanceMap', {
    zoomControl: false,
    attributionControl: false
  }).setView(CONFIG.GUJARAT_CENTER, CONFIG.DEFAULT_ZOOM);

  // CartoDB Dark Matter Tactical Tile Layer
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
    subdomains: 'abcd',
  }).addTo(state.map);

  // Custom Zoom Control at top right
  L.control.zoom({ position: 'topright' }).addTo(state.map);

  // Dedicated Layer Group for Multi-Camera Trajectories
  state.routeLayerGroup = L.layerGroup().addTo(state.map);

  logger("Leaflet Map initialized on Gujarat coordinates [22.2587, 71.1924].");
}

function plotCameraMarkers(cameras) {
  cameras.forEach(cam => {
    if (!cam.latitude || !cam.longitude) return;

    const icon = createTacticalCameraIcon(false);
    const marker = L.marker([cam.latitude, cam.longitude], { icon: icon }).addTo(state.map);

    const popupContent = `
      <div class="p-2 space-y-1">
        <div class="flex items-center justify-between gap-2 border-b border-cyan-500/20 pb-1">
          <span class="font-tactical text-xs font-bold text-cyan-400 tracking-wider">${cam.id}</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-400">ACTIVE</span>
        </div>
        <p class="text-xs font-semibold text-slate-100">${cam.location_name}</p>
        <p class="text-[11px] text-slate-400">District: <span class="text-slate-300 font-medium">${cam.district}</span></p>
        <p class="text-[10px] font-mono text-slate-500">${cam.latitude.toFixed(4)}° N, ${cam.longitude.toFixed(4)}° E</p>
      </div>
    `;
    marker.bindPopup(popupContent);

    state.cameraMarkers.set(cam.id, {
      marker: marker,
      data: cam
    });
  });

  state.activeCamerasCount = cameras.length;
  updateKPI('activeCameras', state.activeCamerasCount);
}

function highlightCameraMarker(cameraId, durationMs = 8000) {
  const camEntry = state.cameraMarkers.get(cameraId);
  if (!camEntry) return;

  const { marker, data } = camEntry;
  // Set alert icon with red pulse
  marker.setIcon(createTacticalCameraIcon(true));

  // Pan and zoom map to camera location
  state.map.flyTo([data.latitude, data.longitude], 12, {
    animate: true,
    duration: 1.2
  });

  marker.openPopup();

  // Reset back to cyan after duration
  setTimeout(() => {
    marker.setIcon(createTacticalCameraIcon(false));
  }, durationMs);
}


// ==========================================
// REST API Data Loading
// ==========================================

async function loadCameras() {
  try {
    const res = await fetch(`${CONFIG.API_BASE}/cameras`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cameras = await res.json();
    logger(`Loaded ${cameras.length} cameras from surveillance API.`);
    plotCameraMarkers(cameras);
  } catch (err) {
    logger(`API offline or unavailable (${err.message}). Using local Gujarat surveillance nodes.`, "warn");
    plotCameraMarkers(FALLBACK_CAMERAS);
  }
}

async function loadInitialLogs() {
  try {
    const res = await fetch(`${CONFIG.API_BASE}/logs?limit=10`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const logs = await res.json();
    if (Array.isArray(logs)) {
      logs.reverse().forEach(log => {
        handleDetectionEvent({
          camera_id: log.camera_id,
          plate_number: log.detected_plate,
          confidence: log.confidence,
          vehicle_type: log.vehicle_type,
          timestamp: log.timestamp
        }, false);
      });
    }
  } catch (err) {
    console.debug("Could not fetch historical logs:", err);
  }
}


// ==========================================
// Real-Time WebSocket Connection
// ==========================================

function initWebSocket() {
  const statusBadge = document.getElementById("wsStatusBadge");
  const statusText = document.getElementById("wsStatusText");

  function setStatus(status) {
    if (!statusBadge || !statusText) return;
    if (status === "connected") {
      statusBadge.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_10px_#10b981] animate-pulse";
      statusText.innerText = "C4I WEBSOCKET LIVE";
      statusText.className = "text-[11px] font-mono font-semibold text-emerald-400";
    } else if (status === "connecting") {
      statusBadge.className = "w-2.5 h-2.5 rounded-full bg-amber-500 animate-ping";
      statusText.innerText = "CONNECTING...";
      statusText.className = "text-[11px] font-mono font-semibold text-amber-400";
    } else {
      statusBadge.className = "w-2.5 h-2.5 rounded-full bg-red-500";
      statusText.innerText = "OFFLINE (RETRYING)";
      statusText.className = "text-[11px] font-mono font-semibold text-red-400";
    }
  }

  setStatus("connecting");
  logger(`Connecting WebSocket to: ${CONFIG.WS_URL}`);

  try {
    state.ws = new WebSocket(CONFIG.WS_URL);

    state.ws.onopen = () => {
      logger("WebSocket connection established with surveillance backend.");
      setStatus("connected");
    };

    state.ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "WATCHLIST_ALERT") {
          handleWatchlistAlert(payload.data);
        } else if (payload.event === "DETECTION_EVENT") {
          handleDetectionEvent(payload.data, true);
        }
      } catch (err) {
        console.error("Error parsing WebSocket payload:", err);
      }
    };

    state.ws.onerror = (err) => {
      console.warn("WebSocket encountered error:", err);
    };

    state.ws.onclose = () => {
      setStatus("disconnected");
      logger(`WebSocket disconnected. Retrying in ${CONFIG.RECONNECT_INTERVAL / 1000}s...`, "warn");
      setTimeout(initWebSocket, CONFIG.RECONNECT_INTERVAL);
    };
  } catch (err) {
    setStatus("disconnected");
    setTimeout(initWebSocket, CONFIG.RECONNECT_INTERVAL);
  }
}


// ==========================================
// Alert & Event Handlers
// ==========================================

function handleDetectionEvent(data, triggerSound = true) {
  state.totalDetections += 1;
  updateKPI('totalDetections', state.totalDetections);

  if (triggerSound) playSonarBlip();

  appendFeedCard({
    type: "DETECTION",
    plate: data.plate_number || "UNKNOWN",
    confidence: data.confidence || 0.85,
    camera_id: data.camera_id || "CAM_01",
    vehicle_type: data.vehicle_type || "vehicle",
    timestamp: data.timestamp || new Date().toISOString()
  });
}

function handleWatchlistAlert(data) {
  state.totalDetections += 1;
  state.watchlistHits += 1;
  updateKPI('totalDetections', state.totalDetections);
  updateKPI('watchlistHits', state.watchlistHits);

  // 1. Play Emergency Siren Audio
  playEmergencySiren();

  // 2. Flash Red Alert Banner at Top of UI
  triggerEmergencyBanner(data);

  // 3. Pulse and Highlight Camera Pin on Leaflet Map
  if (data.camera_id) {
    highlightCameraMarker(data.camera_id, 10000);
  }

  // 4. Open High-Priority Modal Overlay
  showWatchlistModal(data);

  // 5. Prepend Urgent Card to Live Alert Feed
  appendFeedCard({
    type: "ALERT",
    plate: data.plate_number,
    category: data.category || "CRITICAL TARGET",
    owner_name: data.owner_name || "N/A",
    notes: data.notes || "High priority interception advisory",
    camera_id: data.camera_id,
    confidence: data.confidence || 0.95,
    vehicle_type: data.vehicle_type || "vehicle",
    timestamp: data.timestamp || new Date().toISOString()
  });
}


// ==========================================
// UI Rendering & Component Updates
// ==========================================

function updateKPI(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerText = val.toLocaleString();
  el.classList.add("scale-110", "text-cyan-300");
  setTimeout(() => el.classList.remove("scale-110", "text-cyan-300"), 300);
}

function triggerEmergencyBanner(data) {
  const banner = document.getElementById("emergencyAlertBanner");
  const bannerPlate = document.getElementById("bannerPlateNumber");
  const bannerCategory = document.getElementById("bannerCategory");
  const bannerCam = document.getElementById("bannerLocation");

  if (!banner) return;

  bannerPlate.innerText = data.plate_number;
  bannerCategory.innerText = (data.category || "BLACK-LISTED TARGET").toUpperCase();
  bannerCam.innerText = `CAMERA: ${data.camera_id} (${data.district || 'Gujarat'})`;

  banner.classList.remove("hidden");
  banner.classList.add("flex");

  if (state.currentAlertTimeout) clearTimeout(state.currentAlertTimeout);
  state.currentAlertTimeout = setTimeout(() => {
    banner.classList.add("hidden");
    banner.classList.remove("flex");
  }, 12000);
}

function closeEmergencyBanner() {
  const banner = document.getElementById("emergencyAlertBanner");
  if (banner) {
    banner.classList.add("hidden");
    banner.classList.remove("flex");
  }
}

function showWatchlistModal(data) {
  const modal = document.getElementById("targetAlertModal");
  if (!modal) return;

  document.getElementById("modalPlate").innerText = data.plate_number;
  document.getElementById("modalCategory").innerText = (data.category || "WANTED").toUpperCase();
  document.getElementById("modalOwner").innerText = data.owner_name || "Unregistered / Unknown";
  document.getElementById("modalNotes").innerText = data.notes || "Immediate field intercept required by jurisdictional patrol unit.";
  document.getElementById("modalCamera").innerText = `${data.camera_id} - ${data.location_name || 'Surveillance Node'}`;
  document.getElementById("modalTime").innerText = formatTimestamp(data.timestamp);

  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function closeWatchlistModal() {
  const modal = document.getElementById("targetAlertModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
}

function appendFeedCard(item) {
  const container = document.getElementById("alertFeedContainer");
  if (!container) return;

  const isAlert = item.type === "ALERT";
  const card = document.createElement("div");
  card.className = `feed-item-enter p-3 rounded-lg border transition-all duration-300 ${
    isAlert 
      ? "bg-red-950/60 border-red-500/80 shadow-[0_0_15px_rgba(239,68,68,0.3)]" 
      : "bg-slate-900/75 border-slate-800 hover:border-cyan-500/40"
  }`;

  const confPercent = Math.round((item.confidence || 0.8) * 100);
  const timeStr = formatTimestamp(item.timestamp);

  card.innerHTML = `
    <div class="flex items-center justify-between gap-2 mb-2">
      <div class="flex items-center gap-2">
        <span class="${isAlert ? 'hsrp-badge hsrp-badge-alert' : 'hsrp-badge'} font-mono-plate text-xs tracking-wider">
          ${item.plate}
        </span>
        ${isAlert ? `<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-600 text-white tracking-wide animate-pulse">${item.category}</span>` : ''}
      </div>
      <span class="text-[10px] text-slate-400 font-mono">${timeStr}</span>
    </div>

    <div class="flex items-center justify-between text-xs text-slate-300">
      <div class="flex items-center gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full ${isAlert ? 'bg-red-500' : 'bg-cyan-400'}"></span>
        <span class="font-medium">${item.camera_id}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-[11px] text-slate-400 capitalize">${item.vehicle_type}</span>
        <span class="px-1.5 py-0.2 rounded text-[10px] font-mono ${confPercent > 80 ? 'text-emerald-400 bg-emerald-950/40' : 'text-amber-400 bg-amber-950/40'}">
          ${confPercent}%
        </span>
      </div>
    </div>
    ${isAlert && item.owner_name ? `<p class="mt-1.5 text-[11px] text-red-200 border-t border-red-500/20 pt-1"><span class="text-slate-400">Owner:</span> ${item.owner_name}</p>` : ''}
  `;

  // Prepend new card
  container.insertBefore(card, container.firstChild);

  // Prune feed if exceeding maximum items
  while (container.children.length > CONFIG.MAX_FEED_ITEMS) {
    container.removeChild(container.lastChild);
  }
}

function formatTimestamp(ts) {
  if (!ts) return new Date().toLocaleTimeString('en-IN', { hour12: false });
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-IN', { hour12: false });
  } catch {
    return ts;
  }
}

function updateClock() {
  const clockEl = document.getElementById("istClock");
  if (!clockEl) return;
  const now = new Date();
  clockEl.innerText = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + " IST";
}

function logger(msg, level = "info") {
  const prefix = "[COMMAND CENTER]";
  if (level === "warn") console.warn(prefix, msg);
  else if (level === "error") console.error(prefix, msg);
  else console.log(prefix, msg);
}


// ==========================================
// Simulator & Testing Utility
// ==========================================

window.simulateDetection = function() {
  const samplePlates = ["GJ01BK7788", "GJ27CR4040", "GJ03DE9911", "GJ06MN1200", "GJ18ZZ4321"];
  const sampleCams = ["CAM_AHM_SG_01", "CAM_SUR_ATH_02", "CAM_VAD_ALK_03", "CAM_RAJ_TRI_04", "CAM_GND_INF_05"];
  const vehicles = ["car", "truck", "motorcycle", "bus"];

  const randomPlate = samplePlates[Math.floor(Math.random() * samplePlates.length)];
  const randomCam = sampleCams[Math.floor(Math.random() * sampleCams.length)];
  const randomVehicle = vehicles[Math.floor(Math.random() * vehicles.length)];

  handleDetectionEvent({
    camera_id: randomCam,
    plate_number: randomPlate,
    confidence: Number((0.75 + Math.random() * 0.22).toFixed(2)),
    vehicle_type: randomVehicle,
    timestamp: new Date().toISOString()
  });
};

window.simulateWatchlistAlert = function() {
  const targets = [
    {
      plate_number: "GJ01AB1234",
      category: "STOLEN VEHICLE",
      owner_name: "Ramesh Patel",
      notes: "Intercept order active: Stolen high-value SUV reported in Ahmedabad.",
      camera_id: "CAM_AHM_SG_01",
      location_name: "SG Highway - ISKCON Cross Road",
      district: "Ahmedabad",
      latitude: 23.0305,
      longitude: 72.5074
    },
    {
      plate_number: "GJ05XY9876",
      category: "WANTED TARGET",
      owner_name: "Karan Shah",
      notes: "Armed syndicate suspect vehicle. Intercept with caution.",
      camera_id: "CAM_SUR_ATH_02",
      location_name: "Athwa Gate Junction",
      district: "Surat",
      latitude: 21.1834,
      longitude: 72.8105
    }
  ];

  const target = targets[Math.floor(Math.random() * targets.length)];
  handleWatchlistAlert({
    ...target,
    confidence: 0.94,
    vehicle_type: "car",
    timestamp: new Date().toISOString()
  });
};

window.toggleAudio = function() {
  state.soundEnabled = !state.soundEnabled;
  const btn = document.getElementById("audioToggleBtn");
  if (btn) {
    btn.innerHTML = state.soundEnabled
      ? `<svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg><span class="text-xs text-slate-300">Audio ON</span>`
      : `<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg><span class="text-xs text-slate-400">Muted</span>`;
  }
};

window.closeEmergencyBanner = closeEmergencyBanner;
window.closeWatchlistModal = closeWatchlistModal;

// ==========================================
// Multi-Camera Vehicle Route Tracking & GIS Mapping
// ==========================================

async function trackVehicleRoute(plateNumber) {
  if (!plateNumber) return;
  const cleanPlate = plateNumber.trim().replace(/[\s-]/g, '').toUpperCase();

  logger(`Fetching multi-camera trajectory for target: ${cleanPlate}`);

  const trackBtn = document.getElementById("trackRouteBtn");
  if (trackBtn) {
    trackBtn.disabled = true;
    trackBtn.innerHTML = `
      <svg class="w-3.5 h-3.5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="10" stroke-width="4" class="opacity-25"></circle>
        <path d="M4 12a8 8 0 018-8v8H4z" class="opacity-75"></path>
      </svg>
      Tracking...
    `;
  }

  try {
    const res = await fetch(`${CONFIG.API_BASE}/track-vehicle/${encodeURIComponent(cleanPlate)}`);
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const trail = await res.json();

    if (!trail || trail.length === 0) {
      alert(`No surveillance sightings recorded in database for plate: ${cleanPlate}`);
      return;
    }

    // Clear previous route layers
    if (state.routeLayerGroup) {
      state.routeLayerGroup.clearLayers();
    }

    state.activeTrackedPlate = cleanPlate;

    // Filter valid GPS coordinates
    const validHits = trail.filter(h => typeof h.latitude === 'number' && typeof h.longitude === 'number');
    if (validHits.length === 0) {
      alert(`Sightings found, but coordinates are missing for plate: ${cleanPlate}`);
      return;
    }

    const latlngs = validHits.map(h => [h.latitude, h.longitude]);

    // 1. Glowing outer trajectory line
    if (latlngs.length > 1) {
      L.polyline(latlngs, {
        color: '#b91c1c',
        weight: 7,
        opacity: 0.45,
        lineCap: 'round',
        lineJoin: 'round'
      }).addTo(state.routeLayerGroup);

      // 2. Animated tactical dashed polyline
      L.polyline(latlngs, {
        color: '#ef4444',
        weight: 3.5,
        opacity: 0.95,
        lineCap: 'round',
        lineJoin: 'round',
        className: 'leaflet-route-animated'
      }).addTo(state.routeLayerGroup);
    }

    // 3. Numbered sequence markers (1, 2, 3...) at each visited node
    let lastMarker = null;
    validHits.forEach((hit, idx) => {
      const isStart = idx === 0;
      const isEnd = idx === validHits.length - 1;
      let badgeClass = "sequence-marker";
      if (isStart) badgeClass += " sequence-marker-start";
      else if (isEnd) badgeClass += " sequence-marker-end";

      const seqIcon = L.divIcon({
        className: 'sequence-marker-container',
        html: `<div class="${badgeClass}">${idx + 1}</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13],
        popupAnchor: [0, -13]
      });

      const seqMarker = L.marker([hit.latitude, hit.longitude], {
        icon: seqIcon,
        zIndexOffset: 1000 + idx
      }).addTo(state.routeLayerGroup);

      const timeStr = formatTimestamp(hit.timestamp);
      const confPct = Math.round((hit.confidence || 0.85) * 100);

      const popupHtml = `
        <div class="p-2 space-y-1 min-w-[200px]">
          <div class="flex items-center justify-between gap-2 border-b border-red-500/30 pb-1">
            <span class="font-tactical text-xs font-bold text-red-400 tracking-wider">STOP #${idx + 1}</span>
            <span class="font-mono text-[10px] text-slate-400">${timeStr}</span>
          </div>
          <p class="text-xs font-semibold text-slate-100">${hit.location_name}</p>
          <div class="text-[11px] text-slate-300 flex items-center justify-between">
            <span>District: <strong>${hit.district}</strong></span>
            <span class="font-mono text-cyan-400">${hit.camera_id}</span>
          </div>
          <div class="text-[10px] text-slate-400 flex items-center justify-between pt-1 border-t border-slate-800">
            <span>Vehicle: <strong class="capitalize text-slate-200">${hit.vehicle_type || 'vehicle'}</strong></span>
            <span class="text-emerald-400 font-mono">${confPct}%</span>
          </div>
        </div>
      `;
      seqMarker.bindPopup(popupHtml);

      if (isEnd) {
        lastMarker = seqMarker;
      }
    });

    // 4. Zoom map to fit the route
    if (latlngs.length > 1) {
      const bounds = L.latLngBounds(latlngs);
      state.map.fitBounds(bounds, {
        padding: [70, 70],
        maxZoom: 13,
        animate: true,
        duration: 1.2
      });
    } else {
      state.map.flyTo(latlngs[0], 12, { animate: true, duration: 1.0 });
    }

    if (lastMarker) {
      setTimeout(() => lastMarker.openPopup(), 1200);
    }

    // 5. Update route info status pill
    const infoPill = document.getElementById("routeInfoPill");
    const infoPlate = document.getElementById("routeInfoPlate");
    const infoSummary = document.getElementById("routeInfoSummary");
    if (infoPill && infoPlate && infoSummary) {
      infoPlate.innerText = cleanPlate;
      const firstLoc = validHits[0].location_name.split('-')[0].trim();
      const lastLoc = validHits[validHits.length - 1].location_name.split('-')[0].trim();
      infoSummary.innerText = `${validHits.length} sightings (${firstLoc} → ${lastLoc})`;
      infoPill.classList.remove("hidden");
      infoPill.classList.add("flex");
    }

    const searchInput = document.getElementById("vehicleSearchInput");
    if (searchInput) searchInput.value = cleanPlate;

    logger(`Successfully mapped trajectory for ${cleanPlate}: ${validHits.length} camera hits.`);

  } catch (err) {
    logger(`Error tracking vehicle route: ${err.message}`, "error");
    alert(`Failed to track vehicle: ${err.message}`);
  } finally {
    if (trackBtn) {
      trackBtn.disabled = false;
      trackBtn.innerHTML = `
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
        </svg>
        Track Route
      `;
    }
  }
}

function clearVehicleRoute() {
  if (state.routeLayerGroup) {
    state.routeLayerGroup.clearLayers();
  }
  state.activeTrackedPlate = null;

  const infoPill = document.getElementById("routeInfoPill");
  if (infoPill) {
    infoPill.classList.add("hidden");
    infoPill.classList.remove("flex");
  }

  const searchInput = document.getElementById("vehicleSearchInput");
  if (searchInput) searchInput.value = "";

  state.map.flyTo(CONFIG.GUJARAT_CENTER, CONFIG.DEFAULT_ZOOM, {
    animate: true,
    duration: 1.2
  });

  logger("Cleared active vehicle trajectory.");
}

function exportActiveRouteCSV() {
  const inputEl = document.getElementById("vehicleSearchInput");
  const plate = state.activeTrackedPlate || (inputEl ? inputEl.value.trim() : "");
  if (!plate) {
    alert("Please enter or select a vehicle registration plate to export.");
    return;
  }
  const cleanPlate = plate.replace(/[\s-]/g, '').toUpperCase();
  const exportUrl = `${CONFIG.API_BASE}/export-route/${encodeURIComponent(cleanPlate)}`;
  logger(`Opening CSV download for ${cleanPlate}: ${exportUrl}`);
  window.open(exportUrl, "_blank");
}

function trackVehicleFromInput() {
  const input = document.getElementById("vehicleSearchInput");
  if (!input || !input.value.trim()) {
    alert("Please enter a registration plate number (e.g., GJ01AB1234)");
    return;
  }
  trackVehicleRoute(input.value.trim());
}

function setSearchPlate(plate) {
  const input = document.getElementById("vehicleSearchInput");
  if (input) input.value = plate;
  trackVehicleRoute(plate);
}

function trackFromModal() {
  const modalPlate = document.getElementById("modalPlate");
  if (modalPlate && modalPlate.innerText.trim()) {
    const plate = modalPlate.innerText.trim();
    closeWatchlistModal();
    setSearchPlate(plate);
  }
}

window.trackVehicleRoute = trackVehicleRoute;
window.clearVehicleRoute = clearVehicleRoute;
window.exportActiveRouteCSV = exportActiveRouteCSV;
window.trackVehicleFromInput = trackVehicleFromInput;
window.setSearchPlate = setSearchPlate;
window.trackFromModal = trackFromModal;


// ==========================================
// Initialization Lifecycle
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadCameras();
  loadInitialLogs();
  initWebSocket();

  updateClock();
  setInterval(updateClock, 1000);

  // Initialize audio context on first user click anywhere
  window.addEventListener("click", () => {
    getAudioContext();
  }, { once: true });
});
