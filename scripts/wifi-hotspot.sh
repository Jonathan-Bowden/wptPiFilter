#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/default/vmc-wxcvr ]]; then
  # shellcheck disable=SC1091
  source /etc/default/vmc-wxcvr
else
  echo "/etc/default/vmc-wxcvr not found"
  exit 1
fi

SSID="${SSID:-VMC-WXCVR}"
WIFI_PSK="${WIFI_PSK:-vehicle1}"
WLAN_IFACE="${WLAN_IFACE:-wlan0}"

sudo systemctl stop hostapd dnsmasq

nmcli radio wifi on

# Create/bring up hotspot
nmcli device wifi hotspot ifname "${WLAN_IFACE}" ssid "${SSID}" password "${WIFI_PSK}" || true

# Harden WPA2-PSK CCMP settings
nmcli con modify Hotspot 802-11-wireless-security.key-mgmt wpa-psk
nmcli con modify Hotspot 802-11-wireless-security.proto rsn
nmcli con modify Hotspot 802-11-wireless-security.group ccmp
nmcli con modify Hotspot 802-11-wireless-security.pairwise ccmp
nmcli con modify Hotspot 802-11-wireless-security.psk "${WIFI_PSK}"

# Hotspot AP mode, 2.4 GHz band, and shared IPv4 (NAT)
nmcli con modify Hotspot 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared

# Ensure it's up
nmcli con up Hotspot || true

# Remove NM's shared nft table if it conflicts with our rules
nft delete table ip nm-shared-${WLAN_IFACE} 2>/dev/null || true
nft delete table ip nm-shared-wlan0 2>/dev/null || true
``