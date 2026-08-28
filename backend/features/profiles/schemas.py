"""Request models for the profile API — the shape a BrewZilla profile is written in.

Kept out of router.py so producers of profiles (features/recipes/brewzilla_compiler.py)
can target this shape without importing the router that consumes them.
"""

from pydantic import BaseModel


class AlertIn(BaseModel):
    id: str | None = None
    alertText: str | None = None
    trigger: str | None = None
    operator: str | None = None
    temperature: float | None = None
    gravity: float | None = None
    length: int | None = None  # step-level alerts only (trigger=Duration); RAPT Int32


class StepIn(BaseModel):
    id: str | None = None
    name: str | None = None
    order: int = 0
    controlType: str | None = None
    endType: str | None = None
    durationType: str | None = None
    operator: str | None = None
    length: int | None = None  # seconds; RAPT Int32
    temperature: float | None = None
    minTemperature: float | None = None
    maxTemperature: float | None = None
    gravity: float | None = None
    pumpEnabled: bool | None = None
    pumpUtilisation: float | None = None
    heatingUtilisation: float | None = None
    pidEnabled: bool | None = None
    sensorDifferential: float | None = None
    alerts: list[AlertIn] = []


class ProfileIn(BaseModel):
    name: str
    description: str | None = None
    public: bool = False
    profile_type_id: str | None = None
    profile_type_name: str | None = None
    steps: list[StepIn] = []
    alerts: list[AlertIn] = []
