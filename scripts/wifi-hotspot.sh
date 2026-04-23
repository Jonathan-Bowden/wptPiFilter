#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/default/vmc-wxcvr ]]; then
  # shellcheck disable=SC1091
  source /etc/default/vmc-wxcvr
else
  echo "/etc/default/vmc-wxcvr not found"
  exit 1
fi

sudo systemctl stop hostapd dnsmasq

nmcli radio wifi on

for i in $(seq 0 $((AP_COUNT-1))); do
  eval iface="\$AP_${i}_WLAN_IFACE"
  eval ssid="\$AP_${i}_SSID"
  eval psk="\$AP_${i}_WIFI_PSK"
  eval connectionname="\$AP_${i}_CONNECTION_NAME"
  eval subnet="\$AP_${i}_SUBNET"
  nmcli device wifi hotspot ifname "${iface}" con-name "${connectionname}" ssid "${ssid}" password "${psk}" || true
  nmcli con modify "${connectionname}" 802-11-wireless-security.key-mgmt wpa-psk
  nmcli con modify "${connectionname}" 802-11-wireless-security.proto rsn
  nmcli con modify "${connectionname}" 802-11-wireless-security.group ccmp
  nmcli con modify "${connectionname}" 802-11-wireless-security.pairwise ccmp
  nmcli con modify "${connectionname}" 802-11-wireless-security.psk "${psk}"
  nmcli con modify "${connectionname}" ipv4.addresses ${subnet}
  nmcli con modify "${connectionname}" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
  nmcli con up "${connectionname}" || true
done

for i in $(seq 0 $((AP_COUNT-1))); do
  eval iface="\$AP_${i}_WLAN_IFACE"
  eval ssid="\$AP_${i}_SSID"
  eval psk="\$AP_${i}_WIFI_PSK"
  eval connectionname="\$AP_${i}_CONNECTION_NAME"
  eval subnet="\$AP_${i}_SUBNET"
  nft delete table ip nm-shared-${iface} 2>/dev/null || true
done

log "Done."
``