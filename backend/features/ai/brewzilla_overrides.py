"""BrewZilla process overrides: user preferences and explicit process requests that are
not recipe facts. All fields optional; the compiler owns the defaults."""

from pydantic import BaseModel, ConfigDict, Field


class MashTemperatureAddition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=500)
    temperature_c: float = Field(allow_inf_nan=False)


class RestEndAlert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    rest_index: int = Field(ge=0, description="0-based index into recipe.mash.mash_steps")
    text: str = Field(min_length=1, max_length=500)


class BrewZillaOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    include_temperature_alerts: bool | None = None
    include_sparge: bool | None = None
    include_mash_out: bool | None = None
    heat_power_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    rest_power_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    mash_pid_enabled: bool | None = None
    mash_in_temperature_c: float | None = Field(default=None, allow_inf_nan=False)
    mash_in_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    mash_additions: list[MashTemperatureAddition] | None = None
    rest_end_alerts: list[RestEndAlert] | None = None
    mash_out_temperature_c: float | None = Field(default=None, allow_inf_nan=False)
    mash_out_duration_seconds: int | None = Field(default=None, gt=0)
    mash_out_end_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    sparge_temperature_c: float | None = Field(default=None, allow_inf_nan=False)
    sparge_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    boil_temperature_c: float | None = Field(default=None, allow_inf_nan=False)
    whirlpool_temperature_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    whirlpool_end_alert_text: str | None = Field(default=None, min_length=1, max_length=500)
    cooling_temperature_c: float | None = Field(default=None, allow_inf_nan=False)


def merge_overrides(
    user: BrewZillaOverrides | None, extracted: BrewZillaOverrides | None
) -> BrewZillaOverrides:
    """Field-wise merge: an explicitly set user field always wins over the extracted one."""
    merged = (extracted or BrewZillaOverrides()).model_dump(exclude_none=True)
    if user:
        merged.update(user.model_dump(exclude_none=True))
    return BrewZillaOverrides.model_validate(merged)
