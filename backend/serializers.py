"""ORM row -> dict serializers shared by the API routers."""
import json

from db import BrewSession, HydrometerSession


def row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def session_dict(s: HydrometerSession) -> dict:
    """Session row plus derived ABV and apparent attenuation (OG/FG in points)."""
    d = row(s)
    og, fg = s.original_gravity, s.final_gravity
    ok = og is not None and fg is not None and og >= fg
    d["abv"] = round((og - fg) / 7.5, 2) if ok else None
    d["attenuation"] = round((og - fg) / (og - 1000) * 100, 1) if ok and og > 1000 else None
    return d


def brew_session_dict(s: BrewSession) -> dict:
    """Brew session row with the embedded profile (steps/alerts) parsed from JSON."""
    d = row(s)
    d.pop("profile_json", None)
    d["profile"] = json.loads(s.profile_json) if s.profile_json else None
    return d
