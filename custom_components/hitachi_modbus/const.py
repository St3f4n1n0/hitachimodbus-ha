"""Constants for Hitachi ModBus Gateway integration.

Register map: PMML0351A rev.4, section 5.2.1 – HC-A(8/16/64)MB.

Formula: register_address = N_BASE + (slot_id * STRIDE) + offset
  N_BASE   = 2000 (primary) or 20000 (legacy compatibility)
  STRIDE   = 32
  slot_id  = gateway slot 0..15 (from the "Units" table in the gateway)
"""

DOMAIN = "hitachi_modbus"

# ── Config entry keys ──────────────────────────────────────────────────────

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SLAVE_ID = "slave_id"
CONF_N_BASE = "n_base"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults matching the HC-A16MB factory settings
DEFAULT_PORT = 502
DEFAULT_SLAVE_ID = 1
DEFAULT_N_BASE = 2000
DEFAULT_SCAN_INTERVAL = 30  # seconds

# ── Gateway capacity ───────────────────────────────────────────────────────

MAX_UNITS = 16    # HC-A16MB supports up to 16 indoor units
MODBUS_STRIDE = 32

# Temperature sentinel: value returned when a sensor is not connected
TEMP_NOT_AVAILABLE = 255

# ── Gateway low-level registers ────────────────────────────────────────────

GATEWAY_REG_TYPE = 0x0000        # device type
GATEWAY_REG_FIRMWARE = 0x0001    # firmware version (e.g. 0x00FD → H-0253)
GATEWAY_REG_STATUS = 0x0006      # gateway status (2 regs)
GATEWAY_REG_UNITS_TABLE = 0x0064 # start of 16-slot unit address table

# ── Register offsets (section 5.2.1, per indoor unit) ─────────────────────

# Identity (read-only)
OFFSET_EXIST = 0         # 0: not configured, 1: configured
OFFSET_SYS_ADDR = 1      # Outdoor unit address (Ou) – H-LINK system address
OFFSET_UNIT_ADDR = 2     # Indoor unit address  (Iu) – H-LINK unit address

# Control (read/write)
OFFSET_ONOFF_CMD = 3     # 0: Stop, 1: Run
OFFSET_MODE_CMD = 4      # 0: Cool, 1: Dry, 2: Fan, 3: Heat, 4: Auto
OFFSET_FAN_CMD = 5       # 0: Low, 1: Medium, 2: High, 3: High2, 4: Auto
                         # (3 = "High2"/High-H is an optional function that most
                         #  indoor units silently execute as High – not exposed)
OFFSET_TEMP_CMD = 6      # target temperature (°C, integer)
OFFSET_LOUVER_CMD = 7    # 0–7 (7 = Auto)
OFFSET_CENTRAL = 8       # lock bitmask – bit0=OnOff, bit1=Mode,
                         #                bit2=Temp,  bit3=Fan, bit4=Louver

# Status (read-only mirrors of control registers)
OFFSET_ONOFF_STATUS = 9  # 0: Off, 1: On
OFFSET_MODE_STATUS = 10  # same coding as OFFSET_MODE_CMD
OFFSET_FAN_STATUS = 11   # same coding as OFFSET_FAN_CMD
OFFSET_TEMP_STATUS = 12  # current setpoint (°C)
OFFSET_LOUVER_STATUS = 13

# Temperature sensors (read-only, signed 16-bit °C, 2's-complement)
OFFSET_INLET_TEMP = 15       # air inlet / room temperature
OFFSET_OUTLET_TEMP = 16      # air outlet temperature
OFFSET_GAS_PIPE_TEMP = 17
OFFSET_LIQUID_PIPE_TEMP = 18

# Diagnostics (read-only)
OFFSET_ALARM_CODE = 19
OFFSET_COMP_STOP_CAUSE = 20
OFFSET_VALVE_OPENING = 21    # expansion valve  0–100 %
OFFSET_OP_CONDITION = 22     # 0: OFF, 1: Thermo-OFF, 2: Thermo-ON, 3: Alarm

OFFSET_AMBIENT_TEMP = 24     # ambient temperature (signed °C)
OFFSET_RC_TEMP = 25          # remote-control switch temperature

# ── Unit types (PMML0351A §5.2.2 availability columns) ────────────────────

UNIT_TYPE_VRF = "vrf"   # Variable Refrigerant Flow  (multi-split)
UNIT_TYPE_RAC = "rac"   # Room Air Conditioner        (mono-split)
UNIT_TYPE_ATW = "atw"   # Air to Water                (hydronic heat pump)

UNIT_TYPES = [UNIT_TYPE_VRF, UNIT_TYPE_RAC, UNIT_TYPE_ATW]

# ── Per-type HVAC mode availability ───────────────────────────────────────
# Sources: PMML0351A §5.2.2, "Mode setting order" availability column.
# ATW controls a water circuit – "mode" maps to heating/cooling of the circuit;
# dry and fan_only have no meaning for a water-based system.

HVAC_MODES_BY_TYPE: dict[str, list[str]] = {
    UNIT_TYPE_VRF: ["off", "cool", "dry", "fan_only", "heat", "heat_cool"],
    UNIT_TYPE_RAC: ["off", "cool", "dry", "fan_only", "heat", "heat_cool"],
    UNIT_TYPE_ATW: ["off", "cool", "heat"],
}

# ── Per-type fan speed availability ───────────────────────────────────────
# ATW has no fan motor to control.
#
# PMML0351A rev.4 defines register value 3 as "High2" (a.k.a. "High H"), but it
# is an optional indoor-unit function (see optional function EF, "Control in
# Automatic indoor fan speed mode (supporting High H)").  Units that do not
# implement it – RAC wall units in particular – accept the value and run the
# fan at plain High, so the speed is never selectable in practice.  It is
# therefore not offered; incoming status value 3 is reported as "high".

FAN_MODES_BY_TYPE: dict[str, list[str]] = {
    UNIT_TYPE_VRF: ["low", "medium", "high", "auto"],
    UNIT_TYPE_RAC: ["low", "medium", "high", "auto"],
    UNIT_TYPE_ATW: [],  # no fan control
}

# ── Per-type temperature range ─────────────────────────────────────────────
# ATW supplies water to a hydronic circuit; the useful range is wider.
# Format: (min °C, max °C, step °C)

TEMP_RANGE_BY_TYPE: dict[str, tuple[float, float, float]] = {
    UNIT_TYPE_VRF: (16.0, 32.0, 1.0),
    UNIT_TYPE_RAC: (16.0, 32.0, 1.0),
    UNIT_TYPE_ATW: (0.0, 80.0, 1.0),
}

# ── ATW §5.2.2 address space (HC-A(16/64)MB only) ────────────────────────────
# Formula: ATW_N_BASE + slot_id * ATW_STRIDE + offset
# Single read window covers control (50-86) + status (100-167) in 118 regs.
ATW_N_BASE     = 5000
ATW_STRIDE     = 200
ATW_READ_START = 50     # first offset in the read block
ATW_READ_COUNT = 118    # offsets 50..167 inclusive (< 125 Modbus limit)

# ATW control offsets (Read/Write), §5.2.2 ATW column
ATW_OFFSET_ONOFF_CMD         = 50   # 0=Stop, 1=Run
ATW_OFFSET_MODE_CMD          = 51   # 0=Cool, 1=Heat
ATW_OFFSET_CIRCUIT1_RUN_CMD  = 52
ATW_OFFSET_HEAT_SETTEMP_CMD  = 55   # Circuit 1 water heating fix setpoint °C (0-80)
ATW_OFFSET_COOL_SETTEMP_CMD  = 56   # Circuit 1 water cooling fix setpoint °C (0-80)
ATW_OFFSET_HEAT_ECO_OFFSET_CMD = 58 # Circuit 1 Heat ECO Offset Temperature (1-10)
ATW_OFFSET_COOL_ECO_OFFSET_CMD = 59 # Circuit 1 Cool ECO Offset Temperature (1-10)
ATW_OFFSET_DHWT_RUN_CMD       = 74   # 0=Stop, 1=Run
ATW_OFFSET_DHWT_SETTEMP_CMD  = 75   # DHW target temperature °C (0-80)
ATW_OFFSET_DHW_BOOST_CMD     = 76   # 0=No request, 1=Request
ATW_OFFSET_DHW_DEMAND_CMD    = 78   # 0=Standard, 1=High demand
ATW_OFFSET_ANTILEG_RUN_CMD   = 81   # 0=Stop, 1=Run
ATW_OFFSET_ANTILEG_SETTEMP_CMD = 82 # AntiLegionella setting temperature °C (0-80)

# ATW status offsets (Read-only), §5.2.2 ATW column
ATW_OFFSET_ONOFF_STATUS      = 100  # 0=Stop, 1=Run
ATW_OFFSET_MODE_STATUS       = 101  # B0=0:Cool/1:Heat  B1=0:Normal/1:Auto
ATW_OFFSET_CIRCUIT1_STATUS   = 102  # Circuit 1 Run/Stop
ATW_OFFSET_HEAT_SETTEMP_ST   = 105  # Circuit 1 water heating fix setpoint status
ATW_OFFSET_COOL_SETTEMP_ST   = 106  # Circuit 1 water cooling fix setpoint status
ATW_OFFSET_HEAT_ECO_OFFSET_ST = 108 # Circuit 1 Heat ECO Offset Temperature status
ATW_OFFSET_COOL_ECO_OFFSET_ST = 109 # Circuit 1 Cool ECO Offset Temperature status
ATW_OFFSET_DHWT_STATUS        = 126  # DHWT Run/Stop
ATW_OFFSET_DHWT_SETTEMP_ST   = 127  # DHWT Setting Temperature status
ATW_OFFSET_DHW_BOOST_STATUS  = 128  # 0=Disable, 1=Enable
ATW_OFFSET_DHW_DEMAND_STATUS = 130  # 0=Standard, 1=High demand
ATW_OFFSET_DHW_TEMP          = 131  # DHW Temperature (-80~100 °C)
ATW_OFFSET_ANTILEG_STATUS    = 135  # AntiLegionella Run/Stop status
ATW_OFFSET_ANTILEG_SETTEMP_ST = 136 # AntiLegionella Setting Temperature status
ATW_OFFSET_SYS_CONFIG        = 140  # System Configuration bitmask
ATW_OFFSET_OP_STATE          = 141  # 0=OFF…11=Alarm
ATW_OFFSET_OUTDOOR_TEMP      = 142  # Outdoor Ambient T° (-80~100)
ATW_OFFSET_WATER_INLET_TEMP  = 143  # Water Inlet T° (-80~100)
ATW_OFFSET_WATER_OUTLET_TEMP = 144  # Water Outlet T° (-80~100)
ATW_OFFSET_SYS_STATUS2       = 166  # System status 2 bitmask (bit0=Defrost, bit5=Compressor ON)
ATW_OFFSET_ALARM             = 167  # Alarm number

# ── Per-type supported HA ClimateEntityFeature flags ──────────────────────
# ATW has no fan and no louver; VRF/RAC support both.

FEATURES_BY_TYPE: dict[str, list[str]] = {
    UNIT_TYPE_VRF: ["target_temperature", "fan_mode"],
    UNIT_TYPE_RAC: ["target_temperature", "fan_mode"],
    UNIT_TYPE_ATW: ["target_temperature"],
}

# ── Value maps (shared across types) ──────────────────────────────────────

# HVAC mode: Modbus value ↔ Home Assistant string
MODBUS_TO_HA_MODE: dict[int, str] = {
    0: "cool",
    1: "dry",
    2: "fan_only",
    3: "heat",
    4: "heat_cool",
}
HA_MODE_TO_MODBUS: dict[str, int] = {v: k for k, v in MODBUS_TO_HA_MODE.items()}

# Fan speed: Modbus value → Home Assistant string.
# Value 3 ("High2") is folded into "high": the units that do not implement it
# run at High anyway, and the ones that do never report it as a distinct speed.
MODBUS_TO_HA_FAN: dict[int, str] = {
    0: "low",
    1: "medium",
    2: "high",
    3: "high",
    4: "auto",
}

# Home Assistant string → Modbus value (declared explicitly: the map above is
# not injective, so it cannot simply be inverted).
HA_FAN_TO_MODBUS: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "auto": 4,
}

# Fan speeds accepted from old configurations / automations that were written
# while "high2" was still offered, so those calls keep working.
LEGACY_FAN_ALIASES: dict[str, str] = {
    "high2": "high",
}
