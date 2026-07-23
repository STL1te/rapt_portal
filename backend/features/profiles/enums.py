"""RAPT profile enum values — canonical source of truth for recipe assembly.

Plain string tuples (not enum.Enum): the recipe AI-wizard feeds them straight
into prompts / a hard JSON schema, and they're JSON-serializable as-is. Values
match RAPT's swagger enums.

Mirrored in frontend/src/types/profile.ts — keep both in sync.
"""

CONTROL_TYPES = ("Target", "Ramp", "FreeRise")
END_TYPES = ("Duration", "Temperature", "Gravity", "GravityVelocity", "Manual")
DURATION_TYPES = ("Start", "Temperature", "Gravity", "GravityVelocity", "Manual")
VALUE_OPERATORS = ("Equals", "LessThan", "GreaterThan")
ALERT_TRIGGERS = ("StepStart", "StepEnd", "Temperature", "Gravity", "GravityVelocity", "Duration")

# device-facing profile types on the account (ProfileTypes/GetAll .name)
PROFILE_TYPES = ("BrewZilla", "Fermentation", "General Temperature Control", "Pill Hydrometer")

# Canonical (id, name) — RAPT's account-global profile type GUIDs, lifted from the
# portal step editor. Same ids the live GetProfiles returns, so we can offer the
# type picker without a prior profile sync. The editor gates its form per type
# (see frontend kindOf): BrewZilla drops FreeRise; Pill Hydrometer has no steps,
# only profile-level alerts; Fermentation / General Temperature Control get FreeRise.
PROFILE_TYPE_OPTIONS = (
    {"id": "feeb7b99-73e7-4549-9787-13095360bf39", "name": "BrewZilla"},
    {"id": "8b2b4ed6-5c66-44ee-9ebf-d916637ccb21", "name": "Fermentation"},
    {"id": "9653305c-7eb5-40f4-b42a-4918876492d3", "name": "General Temperature Control"},
    {"id": "733509c6-6efd-4841-a7b0-c4b951cf1c90", "name": "Pill Hydrometer"},
)

# human-readable option text from the RAPT step editor. Gaps = value not seen in
# sampled recipes yet (fill when it shows up upstream). For the wizard's prompts.
CONTROL_TYPE_LABELS = {
    "Target": "Heat/Cool to target temperature",
    "Ramp": "Gradual ramp to target over length of step",
}
END_TYPE_LABELS = {
    "Duration": "the step timer is finished",
    "Temperature": "the target temperature is reached",
    "Manual": "I press a button on the Device",
}

# step field constraints from the editor form — seed for the wizard's hard schema
STEP_NAME_MIN_LEN = 4
STEP_NAME_MAX_LEN = 50
STEP_REQUIRED_FIELDS = ("name", "controlType", "temperature", "endType")
