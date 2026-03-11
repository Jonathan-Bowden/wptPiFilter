from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Tuple, Any
import struct


# --- Enums -------------------------------------------------------------------

class VMCProtocol(IntEnum):
    VMC = 0
    SP2 = 1


# NOTE: You referenced VMCCommand and VMCProperty in C#, but they were not defined
# in the snippet. Here are placeholders. Replace values with your actual IDs.
class VMCCommand(IntEnum):
    # Placeholder examples:
    # PING = 0x00
    # SET_PROPERTY = 0x01
    # GET_PROPERTY = 0x02
    # ...
    # UNKNOWN = 0x00
    HEARTBEAT = 0x00
    GET_PROPERTY = 0x01
    SET_PROPERTY = 0x02
    SLEEP = 0x03
    WAKE = 0x04
    START_STREAM = 0x07
    STOP_STREAM = 0x08
    STREAM = 0x10
    CAPTURE = 0x0c
    DIAGNOSTICS = 0x0d
    REBOOT = 0x0e
    OTA_UPDATE = 0x0f
    OTA_WIFI_CONFIG = 0x1f
    CMD_EFM8_MSG = 0x20
    DIAGNOSTIC_EXT = 0x50


class VMCProperty(IntEnum):
    WIFI_SSID = 0x0A
    WIFI_PASSWORD = 0x0B
    MAC_ADDRESS = 0x0C
    SERIAL = 0x0D
    MFG_DATE = 0x0E
    PACKED_BY = 0x0F
    SENSOR_TYPE = 0x10
    FACTORY_LOCK = 0x11
    UNLOCK_KEY = 0x12
    SET_UNLOCK_KEY = 0x13
    SENSOR_NAME = 0x15
    PROP_CALDATE = 0x16
    PROP_CALTIME = 0x17
    UNKNOWN_IDENTIFIER = 0x18
    SENSORID = 0x19
    SOMETHING_BOOL = 0x1A
    PROP_WIFI_OVERWRITE = 0x27
    PROP_EFM8_FW_VERSION = 0x28
    FW_VERSION = 0x29
    SLEEP_STATE = 0x30
    STREAM_STATE = 0x31
    SCAN_RATE = 0x32
    SEND_RATE = 0x33
    CALIBRATION = 0x35
    PROP_NWK_AUTH_PROT = 0x36
    PROP_NWK_DHCP_STAT = 0x37
    PROP_NWK_IP_ADDR = 0x38
    PROP_NWK_SUBNET_MASK = 0x39
    PROP_NWK_GATEWAY = 0x3A
    PROP_NWK_HOST_NAME = 0x3B
    PROP_NWK_CA_CERT = 0x3C
    PROP_NWK_CLIENT_CERT = 0x3D
    PROP_NWK_CLIENT_KEY = 0x3E
    PROP_NWK_AP_IDENT = 0x3F
    BATTERY_LEVEL = 0x40
    WIFI_RSSI = 0x41
    WIFI_TX_POWER = 0x42
    WIFI_PRI_CHAN = 0x43
    PROP_CHARG_STATUS = 0x44
    PROP_SENSOR_OFFSET = 0x45
    PROP_SENSOR_GAIN = 0x46
    PROP_ENABLE_CALIBRATION = 0x47
    PROP_EFM8_FW_VARIANT = 0x48
    PROP_SLEEP_TIME = 0x49
    PROP_WAKEUP_INTERVAL = 0x4A
    PROP_LASER_COMMAND = 0x4B
    PROP_PHOTO_CAL_FREQ = 0x4C
    UNKNOWN_SHORT = 0x50
    UNKNOWN_SHORT2 = 0x51


# --- Object to hold a parsed property ---------------------------------------

@dataclass
class VMCProp:
    # Allow unknown keys (not in enum) by storing the raw int
    key: Union[VMCProperty, int]
    value: Any


# --- Single-property parser --------------------------------------------------

def parse_set_property(payload: bytes) -> VMCProp:
    """
    Parse one SET_PROPERTY payload produced by the C# getBytesSet().

    payload layout:
      [0] = key (VMCProperty)
      [1..] = value as defined by key (see below)

    Returns:
      VMCProp(key, value)

    Raises:
      ValueError if payload is too short for the expected type.
    """
    if not payload:
        raise ValueError("Empty payload")

    pid = payload[0]
    key = VMCProperty(pid) if pid in VMCProperty._value2member_map_ else pid

    # Value bytes after the 1-byte key
    data = payload[1:]
    n = len(data)

    # Fixed-width numeric cases
    if key == VMCProperty.SCAN_RATE:
        if n < 2:
            raise ValueError("SCAN_RATE payload too short (need 2 bytes)")
        (val,) = struct.unpack_from("<H", data, 0)  # ushort little-endian
        return VMCProp(key, val)

    if key == VMCProperty.PROP_SENSOR_GAIN:
        if n < 8:
            raise ValueError("PROP_SENSOR_GAIN payload too short (need 8 bytes)")
        (val,) = struct.unpack_from("<d", data, 0)  # double little-endian
        return VMCProp(key, val)

    if key == VMCProperty.PROP_SENSOR_OFFSET:
        if n < 8:
            raise ValueError("PROP_SENSOR_OFFSET payload too short (need 8 bytes)")
        (val,) = struct.unpack_from("<d", data, 0)
        return VMCProp(key, val)

    if key in (VMCProperty.CALIBRATION, VMCProperty.PROP_ENABLE_CALIBRATION):
        if n < 1:
            raise ValueError(f"{getattr(key, 'name', key)} payload too short (need 1 byte)")
        val = data[0]  # single byte, mirrors (byte)value in your C#
        return VMCProp(key, val)

    # String cases: C# encodes: key + UTF-8(value) with NO length prefix.
    # Therefore we interpret "all remaining bytes" as the string content.
    if key in (VMCProperty.SENSOR_NAME, VMCProperty.SENSORID,
               VMCProperty.PROP_CALDATE, VMCProperty.PROP_CALTIME):
        try:
            s = data.decode("utf-8")
        except UnicodeDecodeError:
            # If robustness > strictness desired, you can use errors="replace" or "ignore".
            s = data.decode("utf-8", errors="replace")
        return VMCProp(key, s)

    # Default: only the key was sent (no value bytes)
    return VMCProp(key, None)


# --- Packet ------------------------------------------------------------------

@dataclass(eq=True, frozen=False)
class VMCPacket:
    """
    Python equivalent of the C# VMCPacket.
    Mirrors header layout and serialization logic:

    For title == "VMC":
        [0..2] title bytes
        [3]    flags (1 byte)
        [4..5] packetID (little-endian Int16)
        [6]    command (1 byte)
        [7]    payloadLen (1 byte)
        [8..]  data (payloadLen bytes)

    For other titles (e.g. "SP2"):
        [0..2] title bytes
        [3]    flags
        [4..5] packetID (little-endian Int16)
        [6]    command
        [7]    channel
        [8]    payloadLen
        [9..]  data (payloadLen bytes)
    """
    title: str = "VMC"                     # 3 ASCII chars
    flags: int = 0                         # byte
    packet_id: int = 0                     # Int16 (stored as Python int)
    command: VMCCommand = VMCCommand.HEARTBEAT
    channel: int = 0                       # byte
    payload_len: int = 0                   # byte (0..255)
    data: bytes = field(default_factory=bytes)
    endpoint: Optional[Tuple[str, int]] = None  # (ip, port)
    heartbeat: int = 0

    # -- Parsing ---------------------------------------------------------------

    @classmethod
    def from_bytes(cls, received: bytes, endpoint: Optional[Tuple[str, int]] = None) -> "VMCPacket":
        if len(received) < 8:
            raise ValueError("Packet too short to be a valid VMC/SP2 packet")

        # Title is exactly 3 bytes ASCII in your C# code
        title = received[:3].decode("ascii", errors="ignore")

        flags = received[3]
        # Little-endian Int16 to mirror C# BitConverter usage and layout (low then high byte)
        packet_id = struct.unpack_from("<h", received, 4)[0]  # signed Int16
        command = VMCCommand(received[6]) if received[6] in VMCCommand._value2member_map_ else VMCCommand.HEARTBEAT

        if title == "VMC":
            if len(received) < 8:
                raise ValueError("VMC header too short")
            payload_len = received[7]
            max_available = max(0, len(received) - 8)
            actual_len = min(payload_len, max_available)
            data = received[8:8 + actual_len]
            channel = 0
        else:
            if len(received) < 9:
                raise ValueError("Non-VMC header too short (expected channel + payloadLen)")
            channel = received[7]
            payload_len = received[8]
            max_available = max(0, len(received) - 9)
            actual_len = min(payload_len, max_available)
            data = received[9:9 + actual_len]

        return cls(
            title=title,
            flags=flags,
            packet_id=packet_id,
            command=command,
            channel=channel,
            payload_len=payload_len,
            data=data,
            endpoint=endpoint,
            heartbeat=0
        )

    # -- Serialization ---------------------------------------------------------

    def to_bytes(self) -> bytes:
        """
        Mirrors the C# ToBytes() method and layout exactly.
        """
        # Normalize packet_id into signed Int16 range on pack
        pid = self.packet_id
        if not (-32768 <= pid <= 32767):
            # match C# (short) cast behavior: wrap to 16-bit signed
            pid = (pid + 2**15) % 2**16 - 2**15

        if self.title == "VMC":
            # 8 + payload
            header = bytearray(8 + (self.payload_len or 0))
            # title (3 bytes)
            t = (self.title or "VMC").encode("ascii", errors="ignore")[:3]
            if len(t) < 3:
                t = t.ljust(3, b'\x00')
            header[0:3] = t
            header[3] = self.flags & 0xFF
            # packet_id little-endian Int16
            struct.pack_into("<h", header, 4, pid)
            header[6] = int(self.command) & 0xFF
            header[7] = self.payload_len & 0xFF
            if self.data and self.payload_len > 0:
                header[8:8 + self.payload_len] = self.data[:self.payload_len]
            return bytes(header)
        else:
            # 9 + payload
            header = bytearray(9 + (self.payload_len or 0))
            # title (3 bytes)
            t = (self.title or "SP2").encode("ascii", errors="ignore")[:3]
            if len(t) < 3:
                t = t.ljust(3, b'\x00')
            header[0:3] = t
            header[3] = self.flags & 0xFF
            struct.pack_into("<h", header, 4, pid)
            header[6] = int(self.command) & 0xFF
            header[7] = self.channel & 0xFF
            header[8] = self.payload_len & 0xFF
            if self.data and self.payload_len > 0:
                header[9:9 + self.payload_len] = self.data[:self.payload_len]
            return bytes(header)

    # -- Helpers / invariants --------------------------------------------------

    def set_payload(self, data: bytes) -> None:
        """Sets data and recalculates payload_len (clamped to 0..255 to mirror byte)."""
        self.data = bytes(data or b"")
        self.payload_len = min(255, max(0, len(self.data)))

    def __hash__(self) -> int:
        # Reasonable Python hash that includes data content, not just its identity
        return hash((
            self.title,
            self.flags,
            self.packet_id,
            int(self.command),
            self.channel,
            self.payload_len,
            self.data  # bytes are hashable by content
        ))


# --- Property TLV-ish helper -------------------------------------------------

@dataclass
class VMCProp:
    key: VMCProperty
    value: Any

    def get_bytes_set(self) -> bytes:
        """
        Mirrors the C# logic:

        - First byte is the property key (ID)
        - Then property-specific representation:

          SCAN_RATE:               1 + sizeof(ushort)  (little-endian)
          PROP_ENABLE_CALIBRATION: 1 + sizeof(bool)    (1 byte: 0/1)

        For other properties (unknown here), only the key is emitted,
        just like your C# default branch.
        """
        k = int(self.key) & 0xFF

        if self.key == VMCProperty.SCAN_RATE:
            # ushort (little-endian)
            if not isinstance(self.value, int):
                raise TypeError("SCAN_RATE expects an int (0..65535)")
            packed = struct.pack("<H", self.value & 0xFFFF)
            return bytes([k]) + packed

        elif self.key == VMCProperty.PROP_ENABLE_CALIBRATION:
            # bool (1 byte)
            if not isinstance(self.value, (bool, int)):
                raise TypeError("PROP_ENABLE_CALIBRATION expects a bool")
            b = 1 if bool(self.value) else 0
            return bytes([k, b])

        # Default: only the key byte, as in your C# default
        return bytes([k])

    def get_bytes_get(self) -> bytes:
        """Request form: only emits the property key."""
        return bytes([int(self.key) & 0xFF])