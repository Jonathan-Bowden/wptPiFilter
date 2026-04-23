#!/usr/bin/env bash
set -euo pipefail

# Load config
if [[ -f /etc/default/vmc-wxcvr ]]; then
  # shellcheck disable=SC1091
  source /etc/default/vmc-wxcvr
else
  echo "/etc/default/vmc-wxcvr not found"
  exit 1
fi

log() { echo "[nft-apply] $*"; }

# Make ip_forward sure at runtime (persistent is handled by sysctl.d)
sysctl -w net.ipv4.ip_forward=0 >/dev/null

# Ensure policy routing for tproxy marked packets exists
RULE="from all fwmark ${MARK} lookup 100"
if ! ip rule show | grep -q "fwmark .* lookup 100" ; then
  log "Adding ip rule: $RULE"
  ip rule add fwmark "${MARK}" lookup 100 || true
else
  log "ip rule exists"
fi

# Ensure route table 100 routes local to lo
if ! ip route show table 100 | grep -q 'local 0.0.0.0/0 dev lo'; then
  log "Adding route to table 100"
  ip route add local 0.0.0.0/0 dev lo table 100 || true
else
  log "route in table 100 exists"
fi

# Prepare nftables
TABLE="inet tproxy2"

# Create table if not exists
if ! nft list table ${TABLE} >/dev/null 2>&1; then
  log "Creating table ${TABLE}"
  nft add table ${TABLE}
fi

# Flush table safely
log "Flushing ${TABLE}"
nft flush table ${TABLE} || true

# Create chains
log "Creating chains"
nft add chain ${TABLE} divert  '{ type filter hook prerouting priority mangle; }'
nft add chain ${TABLE} preroute '{ type filter hook prerouting priority mangle; }'

# Rules
log "Adding rules"
nft add rule ${TABLE} divert meta l4proto udp socket transparent 1 meta mark set ${MARK} accept


for i in $(seq 0 $((AP_COUNT-1))); do
  eval iface="\$AP_${i}_WLAN_IFACE"
  eval ssid="\$AP_${i}_SSID"
  eval subnet="\$AP_${i}_SUBNET"
  nft add rule ${TABLE} preroute iifname "${iface}" udp dport ${UDP1} tproxy to :${TPROXY_PORT} meta mark set ${MARK} accept
  nft add rule ${TABLE} preroute iifname "${iface}" udp sport ${UDP2} tproxy ip to :${TPROXY_PORT} meta mark set ${MARK} accept
  nft add rule ${TABLE} preroute iifname "${iface}" udp dport ${UDP2} tproxy ip to :${TPROXY_PORT} meta mark set ${MARK} accept
  nft add rule ${TABLE} preroute iifname ${ETH_IFACE} ip daddr ${subnet} udp dport ${UDP1} tproxy ip to :19001 meta mark set 0x1 accept
done


## UDP dst 24680 on WLAN_IFACE -> tproxy to local :TPROXY_PORT
#nft add rule ${TABLE} preroute iifname "${WLAN_IFACE}" udp dport ${UDP1} tproxy to :${TPROXY_PORT} meta mark set ${MARK} accept
#nft add rule ${TABLE} preroute iifname "${WLAN_IFACE2}" udp dport ${UDP1} tproxy to :${TPROXY_PORT} meta mark set ${MARK} accept
#
## UDP src/dst 24681 on WLAN_IFACE -> tproxy to local :TPROXY_PORT
#nft add rule ${TABLE} preroute iifname "${WLAN_IFACE}" udp sport ${UDP2} tproxy ip to :${TPROXY_PORT} meta mark set ${MARK} accept
#nft add rule ${TABLE} preroute iifname "${WLAN_IFACE}" udp dport ${UDP2} tproxy ip to :${TPROXY_PORT} meta mark set ${MARK} accept
#nft add rule ${TABLE} preroute iifname "${WLAN_IFACE2}" udp sport ${UDP2} tproxy ip to :${TPROXY_PORT} meta mark set ${MARK} accept
#nft add rule ${TABLE} preroute iifname "${WLAN_IFACE2}" udp dport ${UDP2} tproxy ip to :${TPROXY_PORT} meta mark set ${MARK} accept
#
## REVERSE (eth0 -> hotspot)
#nft add rule ${TABLE} preroute iifname ${ETH_IFACE} ip daddr 10.42.0.0/24 udp dport ${UDP1} tproxy ip to :19001 meta mark set 0x1 accept
#nft add rule ${TABLE} preroute iifname ${ETH_IFACE} ip daddr 10.42.1.0/24 udp dport ${UDP1} tproxy ip to :19001 meta mark set 0x1 accept

# Bypass (order matters)
nft add rule ${TABLE} preroute fib daddr type local return
nft add rule ${TABLE} preroute udp sport 19001 return
nft add rule ${TABLE} preroute meta mark 0x66 return
nft add rule ${TABLE} preroute meta mark 0x77 return

# Remove NetworkManager's nm-shared table if present (harmless if not)
#nft delete table ip nm-shared-${WLAN_IFACE} 2>/dev/null || true
#nft delete table ip nm-shared-wlan0 2>/dev/null || true
#nft delete table ip nm-shared-${WLAN_IFACE2} 2>/dev/null || true
#nft delete table ip nm-shared-wlan1 2>/dev/null || true

for i in $(seq 0 $((AP_COUNT-1))); do
  nft delete table ip nm-shared-${iface} 2>/dev/null || true
done

log "Done."