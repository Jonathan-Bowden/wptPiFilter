#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run as root"; exit 1; fi

systemctl disable --now nft-apply.service 2>/dev/null || true
rm -f /etc/systemd/system/nft-apply.service
systemctl daemon-reload

crontab -l 2>/dev/null | grep -v 'nft-apply.sh' | crontab - || true

rm -f /etc/NetworkManager/dispatcher.d/99-vmc-wxcvr.sh
rm -f /usr/local/bin/nft-apply.sh
rm -f /usr/local/bin/wifi-hotspot.sh
rm -f /etc/default/vmc-wxcvr
rm -f /etc/sysctl.d/99-vmc-wxcvr.conf
sysctl --system >/dev/null || true

echo "[✓] Uninstalled."