#!/usr/bin/env python3
import importlib
import socket
import struct
import ipaddress
import time
import select
from datetime import datetime
import VMCPacket
VMCPacket = importlib.reload(VMCPacket)

LISTEN_PORT = 19001

# ------------- Networks & Ports -------------
HOTSPOT_NET = ipaddress.ip_network("10.42.0.0/24")

PORT_A = 24680  # bi-directional transparent forwarding (as before)
PORT_B = 24681  # BUFFERED: hotspot -> eth0 (aggregate on flush)

# Where to send buffered aggregate (eth0 side)
BATCH_DEST_IP   = "192.168.1.82"   # <--- legacy/static server (unused by default)
DAQSERVER_IP    = "192.168.1.255"  # <--- default broadcast; updated on START_STREAM
BATCH_DEST_PORT = 24681            # <--- UDP port on that server

# ------------- Marks / routing --------------
SO_MARK  = 36
MARK_FWD = 0x66   # wlan0 -> eth0
MARK_REV = 0x77   # eth0 -> wlan0 (for 24680 reverse)

# ------------- 24680 broadcast remap --------
REBROADCAST_ON_ETH0_FOR_24680 = True
ETH0_BROADCAST_IP             = "192.168.1.255"

# ------------- Socket constants -------------
SOL_IP             = socket.SOL_IP
IP_TRANSPARENT     = 19
IP_RECVORIGDSTADDR = 20
IP_ORIGDSTADDR     = 20

def now():
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]

def is_broadcast_ipv4(ip):
    return ip == "255.255.255.255" or ip.split(".")[-1] == "255"

def parse_origdst_from_cmsgs(ancdata):
    for level, ctype, data in ancdata:
        if level == SOL_IP and ctype == IP_ORIGDSTADDR and len(data) >= 8:
            family, nport, addr_bytes = struct.unpack("!HH4s", data[:8])
            return socket.inet_ntoa(addr_bytes), nport
    return None

# ------------- Stream (re)start gating -------------
# After a HEARTBEAT timeout, we suppress all 24681 sends until NEW
# START_STREAM + NEW SCAN_RATE are received (in any order).
require_restart   = False
need_start_stream = False
have_scan_rate    = False

def enter_stopped_state(reason: str):
    """Force stop of batch sends until NEW START_STREAM + SCAN_RATE are received."""
    global require_restart, need_start_stream, have_scan_rate, _hb_suppressed
    require_restart   = True
    need_start_stream = True
    have_scan_rate    = False
    _hb_suppressed    = True  # for logging tone
    out_socks_rate.clear()    # invalidate previous SCAN_RATE; must be resent
    set_rate(0)               # stop the periodic scheduler
    # Optionally drop buffered samples if you don't want to flush stale data on resume:
    # latest_24681_by_ip.clear()
    print(f"{now()}  [stop] {reason} - transmissions disabled until NEW START_STREAM + SCAN_RATE.", flush=True)

# ------------- Heartbeat gating -------------
HEARTBEAT_TIMEOUT = 5.0  # seconds without HEARTBEAT from eth0 -> pause batch sends


# Initialize as "live" so we don't block at startup unless you prefer otherwise.
# If you want to start paused until first heartbeat, set _last_hb_ts to
# (time.monotonic() - HEARTBEAT_TIMEOUT - 1) instead.
_last_hb_ts = time.monotonic()
_hb_suppressed = False

def hb_ok() -> bool:
    """Return True if a recent HEARTBEAT from eth0 was seen within HEARTBEAT_TIMEOUT."""
    return (time.monotonic() - _last_hb_ts) <= HEARTBEAT_TIMEOUT

def hb_watchdog():
    """Check heartbeat on every loop tick. If timed out, enter stopped state once."""
    if not hb_ok() and not require_restart:
        enter_stopped_state(f"No HEARTBEAT from eth0 for >{HEARTBEAT_TIMEOUT:.1f}s")

def note_hb():
    """Record heartbeat-do NOT resume on its own."""
    global _last_hb_ts
    _last_hb_ts = time.monotonic()
    if require_restart:
        print(f"{now()}  [hb] HEARTBEAT restored (still stopped; waiting for START_STREAM + SCAN_RATE).", flush=True)

# ------------- Rate control -----------------
# max_rate = times per second we FLUSH the 24681 buffer
max_rate = 0.0   # will be set from VMCPacket SCAN_RATE or default below

def set_rate(a: float):
    """Set the max flush rate (Hz). 0 disables flushing."""
    global max_rate
    try:
        a = float(a)
    except Exception:
        return
    if a < 0:
        a = 0.0
    if a > 2000:
        a = 2000.0
    max_rate = a
    if max_rate <= 0:
        print(f"{now()}  [rate] max_rate set to 0 Hz (flush disabled)", flush=True)
    else:
        print(f"{now()}  [rate] max_rate set to {max_rate} Hz (interval {1.0/max_rate:.6f}s)", flush=True)

# Track requested rates by endpoint so you can choose max/min/etc. policy
out_socks_rate = {}  # endpoint -> rate

# ------------- Transparent outbound sockets -
# Cached by (bind_ip, bind_port, mark)
out_socks = {}
def get_or_create_out_sock(bind_ip, bind_port, mark):
    key = (bind_ip, bind_port, mark)
    s = out_socks.get(key)
    if s:
        return s
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(SOL_IP, IP_TRANSPARENT, 1)
    s.setsockopt(socket.SOL_SOCKET, SO_MARK, mark)          # steer via policy tables
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind((bind_ip, bind_port))                            # spoof identity
    out_socks[key] = s
    return s

# ------------- Batch socket (non-transparent)
batch_sock = None
def get_batch_sock():
    global batch_sock
    if batch_sock is None:
        batch_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Mark so it routes out eth0 (table 101) and bypasses PREROUTING
        batch_sock.setsockopt(socket.SOL_SOCKET, SO_MARK, MARK_FWD)
        # No bind: let kernel pick a local port/IP
    return batch_sock

# ------------- 24681 Buffer (latest per device) -------------
# Per spec: key by device "IP endpoint" -> we'll use just src_ip (4 bytes in aggregate)
# Map: src_ip -> (payload: bytes, last_update: float)
latest_24681_by_ip = {}

def build_single_aggregate_frame():
    """
    Build one UDP payload containing, for every device with a buffered value:
      [4B IPv4] [3B ASCII "VMC"] [1B 0x00] [1B type 0xFF] [raw payload]
    Concatenate in deterministic source-IP order.
    """
    if not latest_24681_by_ip:
        return b""
    parts = []
    # Sort by IP so receiver can predict order (optional)
    sources = sorted(latest_24681_by_ip.keys(), key=lambda ip: tuple(map(int, ip.split("."))))
    for src_ip in sources:
        payload, _ts = latest_24681_by_ip[src_ip]
        parts.append(socket.inet_aton(src_ip))  # 4 bytes
        parts.append(b"VMC")                    # 3 bytes ASCII
        parts.append(b"\x00")                   # 1 blank byte
        parts.append(b"\xff")                   # 1 byte data type = 0xFF
        parts.append(payload)                   # raw latest data
    return b"".join(parts)

# Optional: enable a light probe to print average interval every ~100ms at 200Hz
ENABLE_FLUSH_PROBE = False
def probe_flush_rate_hook():
    if not ENABLE_FLUSH_PROBE:
        return
    from collections import deque
    ts = time.perf_counter()
    if not hasattr(get_batch_sock, "_flush_ts"):
        get_batch_sock._flush_ts = deque(maxlen=200)
    dq = get_batch_sock._flush_ts
    dq.append(ts)
    if len(dq) >= 2 and len(dq) % 20 == 0:
        dt = (dq[-1] - dq[0]) / (len(dq) - 1)
        print(f"{now()}  flush avg interval ~{dt*1000:.2f} ms (~{1.0/dt:.1f} Hz)", flush=True)

# ------------- Main loop --------------------
def main():
    global DAQSERVER_IP, _hb_suppressed, require_restart, need_start_stream, have_scan_rate

    # Transparent listener (TPROXY delivery)
    s_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s_in.setsockopt(SOL_IP, IP_TRANSPARENT, 1)
    s_in.setsockopt(SOL_IP, IP_RECVORIGDSTADDR, 1)
    s_in.bind(("0.0.0.0", LISTEN_PORT))
    s_in.setblocking(False)  # non-blocking; we'll use select() with a dynamic timeout

    print(f"[*] Transparent UDP forwarder on :{LISTEN_PORT}", flush=True)
    print(f"    - 24680: inline transparent forward (rate ctrl via VMC SCAN_RATE)", flush=True)
    print(f"    - 24681: BUFFERED latest-per-device -> one aggregate to {DAQSERVER_IP}:{BATCH_DEST_PORT} per tick", flush=True)
    if REBROADCAST_ON_ETH0_FOR_24680:
        print(f"    24680 broadcast remap: WLAN 10.42.0.255 -> ETH0 {ETH0_BROADCAST_IP}", flush=True)
    print("    Ctrl+C to stop.\n", flush=True)

    # Scheduling helpers
    def interval():
        return (1.0 / max_rate) if max_rate > 0 else None

    # Initialize next flush deadline
    iv0 = interval()
    next_flush = time.monotonic() + (iv0 if iv0 else 3600.0)

    while True:
        try:
            # ---- Heartbeat watchdog (always runs, independent of traffic or rate) ----
            hb_watchdog()

            # ---- Periodic flush (drift-free, catch up if late) ----
            now_mono = time.monotonic()
            iv_flush = interval()  # use a separate variable for scheduling
            if iv_flush and now_mono >= next_flush:
                if hb_ok() and not require_restart:
                    frame = build_single_aggregate_frame()
                    if frame:
                        bsock = get_batch_sock()
                        try:
                            #print("send periodic", flush=True)
                            bsock.sendto(frame, (DAQSERVER_IP, BATCH_DEST_PORT))
                            latest_24681_by_ip.clear()
                            probe_flush_rate_hook()
                        except PermissionError:
                            print(f"{now()}  sendto EACCES [BATCH] -> {DAQSERVER_IP}:{BATCH_DEST_PORT} len={len(frame)}", flush=True)
                # advance by whole multiples to catch up without drift (even while paused)
                late = now_mono - next_flush
                steps = int(late // iv_flush) + 1 if late >= 0 else 1
                next_flush += steps * iv_flush

            # ---- Compute dynamic wait until next flush (or finite poll if disabled) ----
            iv_timeout = interval()  # use a fresh reading for timeout decision
            if iv_timeout:
                timeout = max(0.0, next_flush - time.monotonic())
            else:
                timeout = 0.25  # keep loop responsive when rate == 0

            # ---- Wait for readability or timeout (whichever comes first) ----
            r, _, _ = select.select([s_in], [], [], timeout)

            if r:
                # ---- Receive next packet ----
                try:
                    data, anc, flags, src = s_in.recvmsg(65535, 256)
                except BlockingIOError:
                    # spurious wakeup; just continue
                    continue

                src_ip, src_port = src[:2]
                dst = parse_origdst_from_cmsgs(anc)
                if not dst:
                    print(f"{now()}  missing ORIGDST from {src_ip}:{src_port} len={len(data)}", flush=True)
                    continue
                dst_ip, dst_port = dst

                src_in_hotspot = ipaddress.ip_address(src_ip) in HOTSPOT_NET
                dst_in_hotspot = ipaddress.ip_address(dst_ip) in HOTSPOT_NET

                # -------------- 24681: BUFFERED (hotspot -> eth0) --------------
                if src_in_hotspot and (src_port == PORT_B or dst_port == PORT_B):
                    if hb_ok() and not require_restart:
                        if src_ip in latest_24681_by_ip:
                            frame = build_single_aggregate_frame()
                            if frame:
                                bsock = get_batch_sock()
                                #try:
                                    #print("send opportunistic", flush=True)
                                    #bsock.sendto(frame, (DAQSERVER_IP, BATCH_DEST_PORT))
                                    # latest_24681_by_ip.clear()  # keep or clear depending on policy
                                    #probe_flush_rate_hook()
                                #except PermissionError:
                                #    print(f"{now()}  sendto EACCES [BATCH] -> {DAQSERVER_IP}:{BATCH_DEST_PORT} len={len(frame)}", flush=True)
                        else:
                            # Accept new samples only when alive & running
                            latest_24681_by_ip[src_ip] = (data, time.monotonic())
                    # If paused/stopped: do not send and (optionally) do not update buffer
                    continue

                # -------------- 24680: inline transparent forward (as before) --------------
                if (src_port == PORT_A or dst_port == PORT_A):
                    if src_in_hotspot:
                        # FORWARD: spoof client -> eth0
                        mark = MARK_FWD
                        bind_ip, bind_port = src_ip, src_port
                        if REBROADCAST_ON_ETH0_FOR_24680 and is_broadcast_ipv4(dst_ip):
                            dst_ip_send = ETH0_BROADCAST_IP
                        else:
                            dst_ip_send = dst_ip
                    elif dst_in_hotspot:
                        # REVERSE: spoof server -> wlan0
                        mark = MARK_REV
                        bind_ip, bind_port = src_ip, src_port
                        dst_ip_send = dst_ip
                    else:
                        # Fallback as forward
                        mark = MARK_FWD
                        bind_ip, bind_port = src_ip, src_port
                        dst_ip_send = dst_ip

                    # Parse possible VMC control on 24680 and adjust state
                    try:
                        pkt = VMCPacket.VMCPacket.from_bytes(data, endpoint=(dst_ip_send, PORT_B))

                        if pkt.command == VMCPacket.VMCCommand.START_STREAM:
                            # Use the sender as DAQ server when stream starts (reverse direction)
                            if dst_in_hotspot:
                                DAQSERVER_IP = src_ip  # update global
                            if require_restart:
                                need_start_stream = False
                                print(f"{now()}  [ctrl] START_STREAM received.", flush=True)
                                # Resume only if we ALSO got a NEW SCAN_RATE
                                if have_scan_rate:
                                    local_max = max(out_socks_rate.values(), default=0.0)
                                    set_rate(local_max)
                                    require_restart = False
                                    _hb_suppressed = False
                                    iv_re = interval()
                                    next_flush = time.monotonic() + (iv_re if iv_re else 3600.0)
                                    print(f"{now()}  [start] START_STREAM + SCAN_RATE satisfied - resuming batch sends.", flush=True)

                        if pkt.command == VMCPacket.VMCCommand.SET_PROPERTY:
                            prop = VMCPacket.parse_set_property(pkt.data)
                            if prop.key == VMCPacket.VMCProperty.SCAN_RATE:
                                out_socks_rate[pkt.endpoint] = prop.value

                                if require_restart:
                                    have_scan_rate = True
                                    print(f"{now()}  [ctrl] SCAN_RATE={prop.value} received.", flush=True)
                                    # Resume only if we ALSO already saw a NEW START_STREAM
                                    if not need_start_stream:
                                        local_max = max(out_socks_rate.values(), default=0.0)
                                        set_rate(local_max)
                                        require_restart = False
                                        _hb_suppressed = False
                                        iv_re = interval()
                                        next_flush = time.monotonic() + (iv_re if iv_re else 3600.0)


                                        print(f"{now()}  [start] START_STREAM + SCAN_RATE satisfied - resuming batch sends.", flush=True)
                                else:
                                    # Live rate update when already running
                                    local_max = max(out_socks_rate.values(), default=0.0)
                                    if local_max != max_rate:
                                        set_rate(local_max)
                                        iv_re = interval()
                                        next_flush = time.monotonic() + (iv_re if iv_re else 3600.0)

                        if pkt.command == VMCPacket.VMCCommand.STOP_STREAM:
                            # DO NOT require restart on STOP_STREAM (per your requirement)
                            if pkt.endpoint in out_socks_rate:
                                del out_socks_rate[pkt.endpoint]
                            local_max = max(out_socks_rate.values(), default=0.0)
                            if local_max != max_rate:
                                set_rate(local_max)
                                iv_re = interval()
                                next_flush = time.monotonic() + (iv_re if iv_re else 3600.0)

                        if pkt.command == VMCPacket.VMCCommand.HEARTBEAT:
                            if not src_in_hotspot:
                                note_hb()

                    except Exception:
                        # Ignore parse errors; payload may not be a VMC control
                        pass

                    try:
                        s_out = get_or_create_out_sock(bind_ip, bind_port, mark)
                        s_out.sendto(data, (dst_ip_send, dst_port))
                    except PermissionError:
                        print(f"{now()}  sendto EACCES [24680] {bind_ip}:{bind_port} -> {dst_ip_send}:{dst_port}", flush=True)
                    continue

                # -------------- Other UDP --------------
                # Ignore or log if needed
                # print(f"{now()}  OTHER  {src_ip}:{src_port} -> {dst_ip}:{dst_port} len={len(data)}", flush=True)

        except KeyboardInterrupt:
            print("\n[!] Interrupted, shutting down.", flush=True)
            break
        except Exception as e:
            print(f"{now()}  runtime ERROR: {e}", flush=True)

    # Cleanup
    for s in out_socks.values():
        try:
            s.close()
        except Exception:
            pass
    if batch_sock:
        try:
            batch_sock.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
