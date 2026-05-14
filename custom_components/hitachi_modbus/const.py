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
# These exist once for the whole gateway device (not per indoor unit).

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

# ── Value maps ─────────────────────────────────────────────────────────────

# HVAC mode: Modbus value ↔ Home Assistant string
MODBUS_TO_HA_MODE: dict[int, str] = {
    0: "cool",
    1: "dry",
    2: "fan_only",
    3: "heat",
    4: "heat_cool",  # AUTO mode
}
HA_MODE_TO_MODBUS: dict[str, int] = {v: k for k, v in MODBUS_TO_HA_MODE.items()}

# Fan speed: Modbus value ↔ Home Assistant string
MODBUS_TO_HA_FAN: dict[int, str] = {
    0: "low",
    1: "medium",
    2: "high",
    3: "high2",
    4: "auto",
}
HA_FAN_TO_MODBUS: dict[str, int] = {v: k for k, v in MODBUS_TO_HA_FAN.items()}

# Full list of HVAC modes exposed to HA (must include "off")
HVAC_MODES = ["off", "cool", "dry", "fan_only", "heat", "heat_cool"]
FAN_MODES = ["low", "medium", "high", "high2", "auto"]

# Temperature range for the climate entity
TEMP_MIN = 16.0
TEMP_MAX = 32.0
TEMP_STEP = 1.0
