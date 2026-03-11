#!/usr/bin/env bash
# /etc/NetworkManager/dispatcher.d/99-vmc-wxcvr.sh
# Runs when interfaces change state. We apply nft rules when WLAN_IFACE is "up".

set -euo pipefail

IFACE="$1"
ACTION="$2"

CONF="/etc/default/vmc-wxcvr"
WLAN_IFACE="wlan0"

if [[ -f "$CONF" ]]; then
  # shellcheck disable=SC1091
  source "$CONF"
fi

log() { echo "[dispatcher] iface=$IFACE action=$ACTION :: $*"; }

if [[ "$IFACE" == "$WLAN_IFACE" ]]; then
  case "$ACTION" in
    up|vpn-up|connectivity-change)
      log "Applying nft rules via /usr/local/bin/nft-apply.sh"
      /usr/local/bin/nft-apply.sh || true
      ;;
    pre-up|down|vpn-down)
      # nothing for now
      ;;
  esac
fi