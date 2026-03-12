#!/usr/bin/env bash
set -euo pipefail

# === Config (override via env or edit here) ===
: "${APP_DIR:=$(pwd)}"
: "${WLAN_IFACE:=wlan0}"
: "${ETH_IFACE:=eth0}"
: "${SSID:=VMC-WXCVR}"
: "${WIFI_PSK:=vehicle1}"
: "${TPROXY_PORT:=19001}"
: "${MARK:=0x1}"
: "${UDP1:=24680}"
: "${UDP2:=24681}"
: "${VENV_DIR:=.venv}"

# === Checks & deps ===
if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (use: sudo bash install.sh)"
  exit 1
fi

echo "[*] Installing required packages..."
apt-get update -y
# Core runtime and NetworkManager
apt-get install -y python3 python3-venv python3-pip nftables network-manager tcpdump
# Build prerequisites (needed for NetfilterQueue from PyPI)
apt-get install -y python3-dev build-essential libnfnetlink-dev libnetfilter-queue-dev

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
# PyPI modules here (inside venv, avoids PEP 668 issues)
pip install --no-cache-dir NetfilterQueue scapy
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

# === Write a config file used by scripts ===
echo "[*] Writing /etc/default/vmc-wxcvr ..."
cat >/etc/default/vmc-wxcvr <<EOF
WLAN_IFACE="${WLAN_IFACE}"
ETH_IFACE="${ETH_IFACE}"
SSID="${SSID}"
WIFI_PSK="${WIFI_PSK}"
TPROXY_PORT="${TPROXY_PORT}"
MARK="${MARK}"
UDP1="${UDP1}"
UDP2="${UDP2}"
APP_DIR="${APP_DIR}"
VENV_DIR="${VENV_DIR}"
EOF
chmod 0644 /etc/default/vmc-wxcvr

# === Enable IP forwarding persistently ===
echo "[*] Enabling IP forwarding persistently..."
cat >/etc/sysctl.d/99-vmc-wxcvr.conf <<EOF
net.ipv4.ip_forward=1
EOF
sysctl --system >/dev/null

# === NetworkManager dispatcher hook (Wi‑Fi events) ===
# Runs the hotspot script and then nft rules when WLAN_IFACE comes up.
echo "[*] Installing NetworkManager dispatcher hook..."
install -d -m 0755 /etc/NetworkManager/dispatcher.d
cat >/etc/NetworkManager/dispatcher.d/99-vmc-wxcvr.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

IFACE="$1"
ACTION="$2"

CONF="/etc/default/vmc-wxcvr"
WLAN_IFACE="wlan0"

if [[ -f "$CONF" ]]; then
  # shellcheck disable=SC1091
  source "$CONF"
fi

log() { logger -t vmc-wxcvr-dispatcher "iface=$IFACE action=$ACTION :: $*"; echo "[dispatcher] iface=$IFACE action=$ACTION :: $*"; }

# Only handle our WLAN interface on "up"/connectivity events
if [[ "$IFACE" == "$WLAN_IFACE" ]]; then
  case "$ACTION" in
    up|vpn-up|connectivity-change)
      log "Starting hotspot and applying nft rules"
      /usr/local/bin/wifi-hotspot.sh || true
      /usr/local/bin/nft-apply.sh || true
      ;;
  esac
fi
EOF
chmod 0755 /etc/NetworkManager/dispatcher.d/99-vmc-wxcvr.sh

# === systemd service at boot (oneshot, runs hotspot then nft rules) ===
echo "[*] Installing systemd boot service..."
cat >/etc/systemd/system/vmc-wxcvr-setup.service <<'EOF'
[Unit]
Description=VMC-WXCVR: setup hotspot and nft rules at boot
After=network-online.target NetworkManager.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wifi-hotspot.sh
ExecStart=/usr/local/bin/nft-apply.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vmc-wxcvr-setup.service

# === Run once now so the system is immediately configured ===
echo "[*] Running hotspot and nft rules now..."
/usr/local/bin/wifi-hotspot.sh || true
/usr/local/bin/nft-apply.sh || true

echo
echo "[✓] Installation complete."
echo
echo "Services/hooks installed:"
echo "  • systemd: vmc-wxcvr-setup.service (runs at boot)"
echo "  • NetworkManager dispatcher: applies on Wi‑Fi up/enabled"
echo
echo "You can now:"
echo "  - Start/refresh hotspot: sudo /usr/local/bin/wifi-hotspot.sh"
echo "  - Apply nft rules now:   sudo /usr/local/bin/nft-apply.sh"
echo
echo "Verify status with:"
echo "  - systemctl status vmc-wxcvr-setup.service"
echo "  - journalctl -u vmc-wxcvr-setup.service -b"
echo "  - sudo nmcli con show --active"
echo "  - sudo nft list ruleset | sed -n '/table inet tproxy2/,\$p' | head -n 80"