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
