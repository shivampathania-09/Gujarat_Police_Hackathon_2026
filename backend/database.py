"""
Gujarat Police Surveillance - Database Module
SQLAlchemy ORM models, session management, schema initialization, and initial seed data.
"""

import os
from datetime import datetime, timezone
from typing import Generator
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Local SQLite Database Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FILE = os.path.join(BASE_DIR, "surveillance.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

# SQLAlchemy Engine and Session
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Base
Base = declarative_base()


# ==========================================
# ORM Models
# ==========================================

class Camera(Base):
    """
    Surveillance Camera Model
    Stores fixed CCTV camera locations across Gujarat police jurisdictions.
    """
    __tablename__ = "cameras"

    id = Column(String(50), primary_key=True, index=True)
    location_name = Column(String(150), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    district = Column(String(100), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "location_name": self.location_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "district": self.district
        }


class DetectionLog(Base):
    """
    ANPR Detection Log Model
    Stores real-time vehicle plate detections logged by the ANPR pipeline.
    """
    __tablename__ = "detection_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    camera_id = Column(String(50), nullable=False, index=True)
    detected_plate = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    confidence = Column(Float, nullable=False)
    vehicle_type = Column(String(50), nullable=True, default="unknown")

    def to_dict(self):
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "detected_plate": self.detected_plate,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "confidence": self.confidence,
            "vehicle_type": self.vehicle_type
        }


class Watchlist(Base):
    """
    Watchlist Model
    Stores blacklisted or flagged registration numbers for alert triggers.
    """
    __tablename__ = "watchlist"

    plate_number = Column(String(20), primary_key=True, index=True)
    category = Column(String(50), nullable=False)  # 'Stolen', 'Wanted', 'Missing'
    owner_name = Column(String(100), nullable=True)
    notes = Column(String(255), nullable=True)

    def to_dict(self):
        return {
            "plate_number": self.plate_number,
            "category": self.category,
            "owner_name": self.owner_name,
            "notes": self.notes
        }


# ==========================================
# Database Dependency & Helpers
# ==========================================

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a SQLAlchemy session.
    Automatically closes session after request lifecycle.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize SQLite database schema and create all tables.
    """
    print(f"Initializing database at: {DATABASE_FILE}")
    Base.metadata.create_all(bind=engine)
    print("Database tables initialized successfully.")


def seed_initial_data(db: Session = None):
    """
    Populate the database with:
    1. 5 mock surveillance cameras in Gujarat cities (Ahmedabad, Surat, Vadodara, Rajkot, Gandhinagar).
    2. 2 sample blacklisted vehicle plates in the Watchlist table for alert verification.
    """
    owns_session = False
    if db is None:
        db = SessionLocal()
        owns_session = True

    try:
        # 1. 5 Mock Cameras with verified coordinates
        mock_cameras = [
            Camera(
                id="CAM_AHM_SG_01",
                location_name="SG Highway - ISKCON Cross Road",
                latitude=23.0305,
                longitude=72.5074,
                district="Ahmedabad"
            ),
            Camera(
                id="CAM_SUR_ATH_02",
                location_name="Athwa Gate Junction",
                latitude=21.1834,
                longitude=72.8105,
                district="Surat"
            ),
            Camera(
                id="CAM_VAD_ALK_03",
                location_name="Alkapuri Circle",
                latitude=22.3106,
                longitude=73.1812,
                district="Vadodara"
            ),
            Camera(
                id="CAM_RAJ_TRI_04",
                location_name="Trikon Baug Chowk",
                latitude=22.3008,
                longitude=70.8022,
                district="Rajkot"
            ),
            Camera(
                id="CAM_GND_INF_05",
                location_name="Infocity Crossroad, CH-0",
                latitude=23.2156,
                longitude=72.6369,
                district="Gandhinagar"
            ),
        ]

        for cam in mock_cameras:
            existing = db.query(Camera).filter_by(id=cam.id).first()
            if not existing:
                db.add(cam)
                print(f"Added Camera: [{cam.id}] {cam.location_name} ({cam.district})")

        # 2. Sample Watchlist Blacklisted Plates
        mock_watchlist = [
            Watchlist(
                plate_number="GJ01AB1234",
                category="Stolen",
                owner_name="Ramesh Patel",
                notes="Reported stolen near Navrangpura, Ahmedabad. High priority interception."
            ),
            Watchlist(
                plate_number="GJ05XY9876",
                category="Wanted",
                owner_name="Karan Shah",
                notes="Wanted Target - Suspect in inter-district armed robbery syndicate."
            ),
        ]

        # 3. Seed Sample Trajectory Detection Logs for Target Plates
        if db.query(DetectionLog).count() == 0:
            from datetime import timedelta
            base_time = datetime.now(timezone.utc) - timedelta(hours=3)
            sample_trail = [
                # Target 1: GJ01AB1234 moving Gandhinagar -> Ahmedabad -> Vadodara
                DetectionLog(
                    camera_id="CAM_GND_INF_05",
                    detected_plate="GJ01AB1234",
                    timestamp=base_time,
                    confidence=0.91,
                    vehicle_type="car"
                ),
                DetectionLog(
                    camera_id="CAM_AHM_SG_01",
                    detected_plate="GJ01AB1234",
                    timestamp=base_time + timedelta(minutes=45),
                    confidence=0.94,
                    vehicle_type="car"
                ),
                DetectionLog(
                    camera_id="CAM_VAD_ALK_03",
                    detected_plate="GJ01AB1234",
                    timestamp=base_time + timedelta(hours=1, minutes=50),
                    confidence=0.89,
                    vehicle_type="car"
                ),
                # Target 2: GJ05XY9876 moving Rajkot -> Ahmedabad -> Surat
                DetectionLog(
                    camera_id="CAM_RAJ_TRI_04",
                    detected_plate="GJ05XY9876",
                    timestamp=base_time - timedelta(hours=2),
                    confidence=0.88,
                    vehicle_type="truck"
                ),
                DetectionLog(
                    camera_id="CAM_AHM_SG_01",
                    detected_plate="GJ05XY9876",
                    timestamp=base_time - timedelta(minutes=30),
                    confidence=0.93,
                    vehicle_type="truck"
                ),
                DetectionLog(
                    camera_id="CAM_SUR_ATH_02",
                    detected_plate="GJ05XY9876",
                    timestamp=base_time + timedelta(hours=2, minutes=15),
                    confidence=0.96,
                    vehicle_type="truck"
                ),
            ]
            db.add_all(sample_trail)
            print("Added sample trajectory logs for multi-camera route tracking.")

        db.commit()
        print("Initial database seeding completed successfully.")

    except Exception as e:
        db.rollback()
        print(f"Error during database seeding: {e}")
        raise
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    init_db()
    seed_initial_data()
