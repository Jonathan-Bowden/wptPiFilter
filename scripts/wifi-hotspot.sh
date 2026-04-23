#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/default/vmc-wxcvr ]]; then
  # shellcheck disable=SC1091
  source /etc/default/vmc-wxcvr
else
  echo "/etc/default/vmc-wxcvr not found"
  exit 1
fi

#SSID="${SSID:-VMC-WXCVR}"
#WIFI_PSK="${WIFI_PSK:-vehicle1}"
#WLAN_IFACE="${WLAN_IFACE:-wlan0}"
#CONNECTION_NAME="${CONNECTION_NAME:-VMC-WXCVR}"
#SSID2="${SSID2:-PI-HOTSPOT}"
#WIFI_PSK2="${WIFI_PSK2:-vehicle2}"
#WLAN_IFACE2="${WLAN_IFACE2:-wlan1}"
#CONNECTION_NAME2="${CONNECTION_NAME2:-VMC-RALINK}"

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

## Create/bring up hotspot
#nmcli device wifi hotspot ifname "${WLAN_IFACE}" con-name "${CONNECTION_NAME}" ssid "${SSID}" password "${WIFI_PSK}" || true
#
## Harden WPA2-PSK CCMP settings
#nmcli con modify "${CONNECTION_NAME}" 802-11-wireless-security.key-mgmt wpa-psk
#nmcli con modify "${CONNECTION_NAME}" 802-11-wireless-security.proto rsn
#nmcli con modify "${CONNECTION_NAME}" 802-11-wireless-security.group ccmp
#nmcli con modify "${CONNECTION_NAME}" 802-11-wireless-security.pairwise ccmp
#nmcli con modify "${CONNECTION_NAME}" 802-11-wireless-security.psk "${WIFI_PSK}"
#nmcli con modify "${CONNECTION_NAME}" ipv4.addresses 10.42.0.1/24
#
## Hotspot AP mode, 2.4 GHz band, and shared IPv4 (NAT)
#nmcli con modify "${CONNECTION_NAME}" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
#
## Ensure it's up
#nmcli con up "${CONNECTION_NAME}" || true
#
## Create/bring up hotspot
#nmcli device wifi hotspot ifname "${WLAN_IFACE2}" con-name "${CONNECTION_NAME2}" ssid "${SSID2}" password "${WIFI_PSK2}" || true
#
## Harden WPA2-PSK CCMP settings
#nmcli con modify "${CONNECTION_NAME2}" 802-11-wireless-security.key-mgmt wpa-psk
#nmcli con modify "${CONNECTION_NAME2}" 802-11-wireless-security.proto rsn
#nmcli con modify "${CONNECTION_NAME2}" 802-11-wireless-security.group ccmp
#nmcli con modify "${CONNECTION_NAME2}" 802-11-wireless-security.pairwise ccmp
#nmcli con modify "${CONNECTION_NAME2}" 802-11-wireless-security.psk "${WIFI_PSK2}"
#nmcli con modify "${CONNECTION_NAME2}" ipv4.addresses 10.42.1.1/24
#
## Hotspot AP mode, 2.4 GHz band, and shared IPv4 (NAT)
#nmcli con modify "${CONNECTION_NAME2}" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
#
## Ensure it's up
#nmcli con up "${CONNECTION_NAME2}" || true
#
## Remove NM's shared nft table if it conflicts with our rules
#nft delete table ip nm-shared-${WLAN_IFACE} 2>/dev/null || true
#nft delete table ip nm-shared-${WLAN_IFACE2} 2>/dev/null || true
#nft delete table ip nm-shared-wlan0 2>/dev/null || true
``