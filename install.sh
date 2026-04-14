#!/usr/bin/env bash
set -euo pipefail

# === Config (override via env or edit here) ===
: "${APP_DIR:=$(pwd)}"
: "${WLAN_IFACE:=wlan0}"
: "${ETH_IFACE:=eth0}"
: "${SSID:=VMC-WXCVR}"
: "${WIFI_PSK:=vehicle1}"
: "${CONNECTION_NAME:=VMC-WXCVR}"
: "${TPROXY_PORT:=19001}"
: "${MARK:=0x1}"
: "${UDP1:=24680}"
: "${UDP2:=24681}"
: "${VENV_DIR:=.venv}"
: "${WLAN_IFACE2:=wlan1}"
: "${SSID2:=VMC-RALINK}"
: "${WIFI_PSK2:=vehicle2}"
: "${CONNECTION_NAME2:=VMC-RALINK}"
: "${SERIALNUM=21}"

# === Checks & deps ===
if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (use: sudo bash install.sh)"
  exit 1
fi

echo "[*] Installing required packages..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nftables network-manager cron
apt-get install -y libnetfilter-queue-dev python3-pip
apt-get install -y hostapd dnsmasq nftables tcpdump

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli (NetworkManager) not found. Please ensure NetworkManager is installed/enabled."
  exit 1
fi

# === Create venv & install requirements ===
echo "[*] Setting up Python virtual environment in ${APP_DIR}/${VENV_DIR}..."
cd "$APP_DIR"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip
pip3 install --no-cache-dir NetfilterQueue scapy
if [[ -f requirements.txt ]]; then
  pip install -r requirements.txt
else
  echo "No requirements.txt found, skipping pip install."
fi
deactivate

# === Install scripts system-wide ===
echo "[*] Installing scripts to /usr/local/bin..."
install -m 0755 scripts/nft-apply.sh /usr/local/bin/nft-apply.sh
install -m 0755 scripts/wifi-hotspot.sh /usr/local/bin/wifi-hotspot.sh

# Write a config file used by scripts
echo "[*] Writing /etc/default/vmc-wxcvr ..."
cat >/etc/default/vmc-wxcvr <<EOF
[AP]
WLAN_IFACE="${WLAN_IFACE}"
ETH_IFACE="${ETH_IFACE}"
SSID="${SSID}"
WIFI_PSK="${WIFI_PSK}"
CONNECTION_NAME="${VMC-WXCVR}"
TPROXY_PORT="${TPROXY_PORT}"
MARK="${MARK}"
UDP1="${UDP1}"
UDP2="${UDP2}"
APP_DIR="${APP_DIR}"
VENV_DIR="${VENV_DIR}"
WLAN_IFACE2="${WLAN_IFACE2}"
SSID2="${SSID2}"
WIFI_PSK2="${WIFI_PSK2}"
CONNECTION_NAME2="${VMC-RALINK}"
SERIALNUM="${SERIALNUM}"
EOF
chmod 0644 /etc/default/vmc-wxcvr

# === Enable IP forwarding persistently ===
echo "[*] Enabling IP forwarding persistently..."
cat >/etc/sysctl.d/99-vmc-wxcvr.conf <<EOF
net.ipv4.ip_forward=0
EOF
sysctl --system >/dev/null

# === NetworkManager dispatcher hook (Wi-Fi events) ===
echo "[*] Installing NetworkManager dispatcher hook..."
install -d -m 0755 /etc/NetworkManager/dispatcher.d
install -m 0755 system/99-vmc-wxcvr.sh /etc/NetworkManager/dispatcher.d/99-vmc-wxcvr.sh

# === (Optional) systemd service at boot ===
echo "[*] Installing (optional) systemd service to apply nft at boot..."
install -m 0644 system/nft-apply.service /etc/systemd/system/nft-apply.service
systemctl daemon-reload
systemctl enable nft-apply.service

# === Cron @reboot (as requested) ===
echo "[*] Adding cron @reboot entry for nft-apply.sh..."
existing="$(crontab -l 2>/dev/null || true)"
# Add to root's crontab

printf "%s\n%s\n" \
  "$(printf "%s\n" "$existing" | grep -v '/usr/local/bin/nft-apply\.sh' || true)" \
  "@reboot /usr/local/bin/nft-apply.sh >/var/log/nft-apply.log 2>&1" \
  | crontab -
echo "[✓] Cron updated."

#( crontab -l 2>/dev/null | grep -v 'nft-apply.sh' ; echo '@reboot /usr/local/bin/nft-apply.sh >/var/log/nft-apply.log 2>&1' ) | crontab -

echo
echo "[✓] Installation complete."
echo "You can now:"
echo "  - Start/refresh hotspot: sudo /usr/local/bin/wifi-hotspot.sh"
echo "  - Apply nft rules now:   sudo /usr/local/bin/nft-apply.sh"
echo
echo "Rules will be re-applied:"
echo "  • on boot (systemd + cron @reboot)"
echo "  • whenever Wi‑Fi/Hotspot comes up (NetworkManager dispatcher)"