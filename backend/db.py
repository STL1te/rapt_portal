"""SQLAlchemy models and session factory."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Hydrometer(Base):
    __tablename__ = "hydrometers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    gravity: Mapped[float | None] = mapped_column(Float)
    temperature: Mapped[float | None] = mapped_column(Float)
    battery: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[float | None] = mapped_column(Float)
    active_session_id: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class HydrometerSession(Base):
    __tablename__ = "hydrometer_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    hydrometer_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String)
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    original_gravity: Mapped[float | None] = mapped_column(Float)
    final_gravity: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class HydrometerTelemetry(Base):
    __tablename__ = "hydrometer_telemetry"
    __table_args__ = (UniqueConstraint("session_id", "timestamp", name="uq_hydro_session_ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("hydrometer_sessions.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    gravity: Mapped[float | None] = mapped_column(Float)
    gravity_velocity: Mapped[float | None] = mapped_column(Float)
    temperature: Mapped[float | None] = mapped_column(Float)
    battery: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[float | None] = mapped_column(Float)


class Yeast(Base):
    __tablename__ = "yeasts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, index=True)
    product_id: Mapped[str | None] = mapped_column(String)
    laboratory: Mapped[str | None] = mapped_column(String, index=True)
    type: Mapped[str | None] = mapped_column(String, index=True)
    form: Mapped[str | None] = mapped_column(String)
    min_temperature: Mapped[float | None] = mapped_column(Float)
    max_temperature: Mapped[float | None] = mapped_column(Float)
    flocculation: Mapped[str | None] = mapped_column(String)
    attenuation: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class BrewZilla(Base):
    __tablename__ = "brewzillas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    temperature: Mapped[float | None] = mapped_column(Float)
    target_temperature: Mapped[float | None] = mapped_column(Float)
    heating_enabled: Mapped[bool | None] = mapped_column(Boolean)
    heating_utilisation: Mapped[float | None] = mapped_column(Float)
    pump_enabled: Mapped[bool | None] = mapped_column(Boolean)
    pump_utilisation: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[float | None] = mapped_column(Float)
    active_session_id: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class BrewSession(Base):
    __tablename__ = "brew_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    brewzilla_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String)
    profile_id: Mapped[str | None] = mapped_column(String)
    profile_json: Mapped[str | None] = mapped_column(Text)  # embedded profile: name, steps[], alerts
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class BrewTelemetry(Base):
    __tablename__ = "brew_telemetry"
    __table_args__ = (UniqueConstraint("session_id", "timestamp", name="uq_brew_session_ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("brew_sessions.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    temperature: Mapped[float | None] = mapped_column(Float)  # element/kettle temp
    target_temperature: Mapped[float | None] = mapped_column(Float)
    min_target_temperature: Mapped[float | None] = mapped_column(Float)
    max_target_temperature: Mapped[float | None] = mapped_column(Float)
    control_device_temperature: Mapped[float | None] = mapped_column(Float)  # external probe (wort)
    heating_run_time: Mapped[float | None] = mapped_column(Float)  # cumulative seconds
    heating_starts: Mapped[int | None] = mapped_column(Integer)
    auxillary_run_time: Mapped[float | None] = mapped_column(Float)
    auxillary_starts: Mapped[int | None] = mapped_column(Integer)
    profile_step_id: Mapped[str | None] = mapped_column(String)
    profile_step_progress: Mapped[float | None] = mapped_column(Float)  # 0..1 within step
    profile_session_time: Mapped[float | None] = mapped_column(Float)  # seconds into session
    rssi: Mapped[float | None] = mapped_column(Float)


def init_db() -> None:
    Base.metadata.create_all(engine)
