"""
Gujarat Police Surveillance - Core API & WebSocket Server
FastAPI backend providing:
- REST API for Cameras, Watchlists, and Detection Logs
- WebSocket server (/ws) for real-time detection & alert broadcasts
- Asynchronous Background ANPR Stream Processing pipeline
"""

import os
import json
import logging
import asyncio
import threading
from datetime import datetime, timezone
import io
import csv
from typing import List, Dict, Any, Optional, Union
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

import sys
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# Internal modules
try:
    from anpr_engine import ANPREngine
    from database import (
        init_db,
        seed_initial_data,
        get_db,
        SessionLocal,
        Camera,
        DetectionLog,
        Watchlist
    )
except ImportError:
    from backend.anpr_engine import ANPREngine
    from backend.database import (
        init_db,
        seed_initial_data,
        get_db,
        SessionLocal,
        Camera,
        DetectionLog,
        Watchlist
    )

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("GujaratPoliceSurveillanceAPI")

# Global singleton ANPR Engine instance
anpr_engine: Optional[ANPREngine] = None

# Active video streaming task threads registry
active_streams: Dict[str, threading.Event] = {}


# ==========================================
# Application Lifespan (Startup / Shutdown)
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown event lifecycle.
    Initializes database tables, runs initial seed data, and prepares ANPR engine.
    """
    logger.info("Initializing Gujarat Police Surveillance Backend...")
    # 1. Initialize SQLite Database & Seed Data
    init_db()
    seed_initial_data()

    # 2. Lazy or warmup load of ANPR Engine
    global anpr_engine
    anpr_engine = ANPREngine(
        yolo_model_path="yolov8n.pt",
        confidence_threshold=0.40,
        frame_interval=5,
        use_gpu=False
    )
    logger.info("ANPR Engine initialized and ready.")

    yield

    logger.info("Shutting down surveillance service. Stopping active video streams...")
    for cam_id, stop_event in list(active_streams.items()):
        stop_event.set()
    active_streams.clear()


# Initialize FastAPI Application
app = FastAPI(
    title="Gujarat Police Surveillance API",
    description="Real-Time CCTV Video Analytics & ANPR Interception Network",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for Frontend Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# WebSocket Connection Manager
# ==========================================

class ConnectionManager:
    """Manages active WebSocket client connections and facilitates broadcasts."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Active connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcasts a JSON-serializable message payload to all active clients."""
        async with self._lock:
            disconnected_sockets = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception as ex:
                    logger.warning(f"Error broadcasting to client, removing connection: {ex}")
                    disconnected_sockets.append(connection)

            for dead_socket in disconnected_sockets:
                if dead_socket in self.active_connections:
                    self.active_connections.remove(dead_socket)


manager = ConnectionManager()


# ==========================================
# Pydantic Schemas
# ==========================================

class StartStreamRequest(BaseModel):
    video_source: Union[str, int] = Field(
        ...,
        description="Path to video file, RTSP URL stream, or webcam index (0)"
    )
    camera_id: str = Field(
        ...,
        description="ID of the camera corresponding to a registered camera in database"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "video_source": "traffic_surveillance.mp4",
                "camera_id": "CAM_AHM_SG_01"
            }
        }


class StopStreamRequest(BaseModel):
    camera_id: str


# ==========================================
# WebSocket Endpoint
# ==========================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Real-time WebSocket endpoint for the police surveillance dashboard.
    Receives detection events and high-priority watchlist alerts in real-time.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep-alive heartbeat listener
            data = await websocket.receive_text()
            # Respond to ping/heartbeats if needed
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)


# ==========================================
# REST API Endpoints
# ==========================================

@app.get("/api/cameras", summary="Query all registered CCTV cameras")
def get_cameras(db: Session = Depends(get_db)):
    """Return all Gujarat police surveillance cameras with GPS coordinates."""
    cameras = db.query(Camera).all()
    return [cam.to_dict() for cam in cameras]


@app.get("/api/watchlist", summary="Query all blacklisted vehicles")
def get_watchlist(db: Session = Depends(get_db)):
    """Return all active targets/blacklisted license plates."""
    targets = db.query(Watchlist).all()
    return [target.to_dict() for target in targets]


@app.get("/api/logs", summary="Query historical ANPR detection logs")
def get_detection_logs(
    limit: int = 100,
    camera_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Return historical DetectionLog records ordered by timestamp descending."""
    query = db.query(DetectionLog)
    if camera_id:
        query = query.filter(DetectionLog.camera_id == camera_id)
    logs = query.order_by(DetectionLog.timestamp.desc()).limit(limit).all()
    return [log.to_dict() for log in logs]


@app.get("/api/track-vehicle/{plate_number}", summary="Track chronological multi-camera trail of a vehicle")
def track_vehicle_route(plate_number: str, db: Session = Depends(get_db)):
    """
    Query DetectionLog for all records matching plate_number (case-insensitive),
    sorted chronologically ascending, joined with Camera metadata.
    """
    clean_plate = plate_number.replace(" ", "").replace("-", "").upper()

    hits = (
        db.query(DetectionLog, Camera)
        .join(Camera, DetectionLog.camera_id == Camera.id)
        .filter(func.upper(DetectionLog.detected_plate) == clean_plate)
        .order_by(DetectionLog.timestamp.asc())
        .all()
    )

    trail = []
    for log, cam in hits:
        trail.append({
            "id": log.id,
            "camera_id": log.camera_id,
            "detected_plate": log.detected_plate,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "confidence": log.confidence,
            "vehicle_type": log.vehicle_type,
            "location_name": cam.location_name,
            "district": cam.district,
            "latitude": cam.latitude,
            "longitude": cam.longitude
        })

    return trail


@app.get("/api/export-route/{plate_number}", summary="Export vehicle route as downloadable CSV")
def export_vehicle_route(plate_number: str, db: Session = Depends(get_db)):
    """
    Generate and return a downloadable CSV containing the vehicle's chronological trail across cameras.
    Columns: Timestamp, Plate Number, Camera ID, Location Name, District, Latitude, Longitude, Confidence.
    """
    clean_plate = plate_number.replace(" ", "").replace("-", "").upper()

    hits = (
        db.query(DetectionLog, Camera)
        .join(Camera, DetectionLog.camera_id == Camera.id)
        .filter(func.upper(DetectionLog.detected_plate) == clean_plate)
        .order_by(DetectionLog.timestamp.asc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Timestamp",
        "Plate Number",
        "Camera ID",
        "Location Name",
        "District",
        "Latitude",
        "Longitude",
        "Confidence"
    ])

    for log, cam in hits:
        ts_str = log.timestamp.isoformat() if log.timestamp else ""
        writer.writerow([
            ts_str,
            log.detected_plate,
            cam.id,
            cam.location_name,
            cam.district,
            cam.latitude,
            cam.longitude,
            f"{log.confidence:.2f}"
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="route_{clean_plate}.csv"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


# ==========================================
# Background Video Stream Processing
# ==========================================

def process_detection_record(raw_detection_json: str, camera_id: str, loop: asyncio.AbstractEventLoop):
    """
    Synchronous worker callback that:
    1. Parses detection payload.
    2. Writes DetectionLog record to SQLite.
    3. Checks Watchlist table for alert match.
    4. Triggers async WebSocket broadcast via the FastAPI event loop.
    """
    try:
        detection_data = json.loads(raw_detection_json)
    except Exception as e:
        logger.error(f"Failed to parse detection JSON: {e}")
        return

    detected_plate = detection_data.get("plate_number", "").strip().upper()
    confidence = float(detection_data.get("confidence", 0.0))
    vehicle_type = detection_data.get("vehicle_type", "unknown")
    raw_ts = detection_data.get("timestamp")

    # Parse timestamp
    parsed_dt = datetime.now(timezone.utc)
    if raw_ts:
        try:
            parsed_dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except Exception:
            parsed_dt = datetime.now(timezone.utc)

    # Database Operations
    db: Session = SessionLocal()
    try:
        # 1. Save new DetectionLog record
        new_log = DetectionLog(
            camera_id=camera_id,
            detected_plate=detected_plate,
            timestamp=parsed_dt,
            confidence=confidence,
            vehicle_type=vehicle_type
        )
        db.add(new_log)
        db.commit()
        db.refresh(new_log)

        # 2. Query Camera Coordinates
        camera_record = db.query(Camera).filter(Camera.id == camera_id).first()
        cam_lat = camera_record.latitude if camera_record else None
        cam_lon = camera_record.longitude if camera_record else None
        cam_location = camera_record.location_name if camera_record else "Unknown Location"
        cam_district = camera_record.district if camera_record else "Gujarat"

        # 3. Cross-reference plate against Watchlist
        watchlist_match = db.query(Watchlist).filter(Watchlist.plate_number == detected_plate).first()

        if watchlist_match:
            # High Priority Watchlist Target Interception Alert!
            alert_payload = {
                "event": "WATCHLIST_ALERT",
                "data": {
                    **detection_data,
                    "log_id": new_log.id,
                    "category": watchlist_match.category,
                    "owner_name": watchlist_match.owner_name,
                    "notes": watchlist_match.notes,
                    "latitude": cam_lat,
                    "longitude": cam_lon,
                    "location_name": cam_location,
                    "district": cam_district
                }
            }
            logger.warning(
                f"🚨 [WATCHLIST ALERT] Target '{detected_plate}' ({watchlist_match.category}) "
                f"detected at camera {camera_id} ({cam_location})"
            )
            asyncio.run_coroutine_threadsafe(manager.broadcast(alert_payload), loop)
        else:
            # Standard Detection Event
            detection_payload = {
                "event": "DETECTION_EVENT",
                "data": {
                    **detection_data,
                    "log_id": new_log.id,
                    "latitude": cam_lat,
                    "longitude": cam_lon,
                    "location_name": cam_location,
                    "district": cam_district
                }
            }
            asyncio.run_coroutine_threadsafe(manager.broadcast(detection_payload), loop)

    except Exception as ex:
        db.rollback()
        logger.error(f"Error handling detection log persistence: {ex}", exc_info=True)
    finally:
        db.close()


def stream_worker_thread(
    video_source: Union[str, int],
    camera_id: str,
    stop_event: threading.Event,
    loop: asyncio.AbstractEventLoop
):
    """
    Dedicated worker thread running the ANPREngine video processing loop.
    Keeps FastAPI asynchronous event loop completely unblocked.
    """
    logger.info(f"Stream worker started for camera [{camera_id}] with source: {video_source}")

    try:
        # Convert numeric strings (e.g. "0") to int for local webcam testing
        src = int(video_source) if str(video_source).isdigit() else video_source

        # Generator iterating frames and yielding JSON detections
        for raw_detection_json in anpr_engine.process_video_stream(video_source=src, camera_id=camera_id):
            if stop_event.is_set():
                logger.info(f"Stop signal received for camera [{camera_id}]. Exiting stream worker.")
                break

            process_detection_record(
                raw_detection_json=raw_detection_json,
                camera_id=camera_id,
                loop=loop
            )

    except Exception as e:
        logger.error(f"Stream worker encountered error for camera [{camera_id}]: {e}", exc_info=True)
    finally:
        active_streams.pop(camera_id, None)
        logger.info(f"Stream worker terminated for camera [{camera_id}].")


@app.post("/api/start-stream", summary="Start background ANPR video processing stream")
async def start_stream(payload: StartStreamRequest):
    """
    Spawn an asynchronous background task running ANPREngine on the video source.
    Pushes real-time detection logs and Watchlist alerts via WebSockets.
    """
    camera_id = payload.camera_id
    video_source = payload.video_source

    if camera_id in active_streams:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera stream '{camera_id}' is already actively running."
        )

    # Verify camera exists in database
    db = SessionLocal()
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    db.close()
    if not cam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera with ID '{camera_id}' not found in database."
        )

    stop_event = threading.Event()
    active_streams[camera_id] = stop_event

    current_loop = asyncio.get_running_loop()

    # Launch dedicated thread to isolate CPU-intensive OCR/YOLO computation
    thread = threading.Thread(
        target=stream_worker_thread,
        args=(video_source, camera_id, stop_event, current_loop),
        daemon=True,
        name=f"ANPR-Worker-{camera_id}"
    )
    thread.start()

    logger.info(f"Started video stream processing for camera '{camera_id}'.")
    return {
        "status": "success",
        "message": f"ANPR video stream initiated for camera '{camera_id}'.",
        "camera_id": camera_id,
        "video_source": str(video_source)
    }


@app.post("/api/stop-stream", summary="Stop active ANPR video stream")
async def stop_stream(payload: StopStreamRequest):
    """Stop an ongoing video processing stream for a specified camera."""
    camera_id = payload.camera_id
    stop_event = active_streams.get(camera_id)
    if not stop_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active stream found for camera '{camera_id}'."
        )

    stop_event.set()
    return {
        "status": "success",
        "message": f"Stop signal dispatched for camera '{camera_id}'."
    }


@app.get("/api/streams", summary="List all currently active video streams")
def list_active_streams():
    """Returns list of camera IDs with running video streams."""
    return {"active_camera_streams": list(active_streams.keys())}


# ==========================================
# Root Health Check
# ==========================================

@app.get("/", summary="Surveillance System Health")
def root_status():
    return {
        "system": "Gujarat Police Surveillance - Real-Time ANPR Engine",
        "status": "online",
        "version": "1.0.0",
        "active_streams": len(active_streams)
    }
