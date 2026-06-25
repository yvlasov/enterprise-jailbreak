#!/bin/bash
set -e

: "${VPN_TYPE:?VPN_TYPE must be set: 'checkpoint' or 'forticlient'}"

# Load secrets from files if present (Docker secrets mount at /run/secrets/)
[ -f /run/secrets/checkpoint_vpn_password ] && export CHECKPOINT_VPN_PASSWORD=$(cat /run/secrets/checkpoint_vpn_password)
[ -f /run/secrets/forti_vpn_password ]       && export FORTI_VPN_PASSWORD=$(cat /run/secrets/forti_vpn_password)

case "$VPN_TYPE" in

  checkpoint)
    : "${CHECKPOINT_VPN_SERVER:?CHECKPOINT_VPN_SERVER required}"
    : "${CHECKPOINT_VPN_USER:?CHECKPOINT_VPN_USER required}"
    VPN_IFACE="${CHECKPOINT_VPN_IFACE:-snx-tun}"
    VPN_HEALTH_IP="${CHECKPOINT_VPN_HEALTH_IP:-10.226.0.5}"

    _PASS_B64=""
    [ -n "$CHECKPOINT_VPN_PASSWORD" ] && _PASS_B64=$(printf '%s' "$CHECKPOINT_VPN_PASSWORD" | base64)
    cat > /root/.config/snx-rs/snx-rs.conf <<EOF
login-type=${CHECKPOINT_VPN_LOGIN_TYPE:-vpn_Indeed}
user-name=${CHECKPOINT_VPN_USER}
${_PASS_B64:+password=${_PASS_B64}}
server-name=${CHECKPOINT_VPN_SERVER}
ignore-server-cert=${CHECKPOINT_VPN_IGNORE_CERT:-true}
log-level=warning
tunnel-type=${CHECKPOINT_VPN_TUNNEL_TYPE:-ssl}
no-dns=true
EOF

    # Start snx-rs daemon in command mode (snxctl requires this)
    snx-rs --mode command --config-file /root/.config/snx-rs/snx-rs.conf &

    sed "s/__VPN_HEALTH_IP__/${VPN_HEALTH_IP}/" /config/procwatch-checkpoint.yaml > /run/procwatch.yaml
    export PROCWATCH_CONFIG=/run/procwatch.yaml
    ;;

  forticlient)
    : "${FORTI_VPN_HOST:?FORTI_VPN_HOST required}"
    : "${FORTI_VPN_USER:?FORTI_VPN_USER required}"
    : "${FORTI_VPN_PASSWORD:?FORTI_VPN_PASSWORD required}"
    VPN_IFACE="${FORTI_VPN_IFACE:-ppp0}"
    VPN_HEALTH_IP="${FORTI_VPN_HEALTH_IP:-8.8.8.8}"

    sed "s/__VPN_HEALTH_IP__/${VPN_HEALTH_IP}/" /config/procwatch-forticlient.yaml > /run/procwatch.yaml
    export PROCWATCH_CONFIG=/run/procwatch.yaml
    ;;

  *)
    echo "ERROR: VPN_TYPE must be 'checkpoint' or 'forticlient', got: $VPN_TYPE" >&2
    exit 1
    ;;
esac

# Patch danted external interface into a runtime copy
sed "s/^external: .*/external: ${VPN_IFACE}/" /config/danted.conf > /run/danted.conf

# Start dnsmasq
dnsmasq --conf-file=/config/dnsmasq.conf --keep-in-foreground &


# Start dante once VPN interface appears
if [ "${START_DANTE:-1}" = "1" ]; then
    (
        echo "Waiting for VPN interface ${VPN_IFACE}..."
        until ip link show "${VPN_IFACE}" &>/dev/null; do
            sleep 2
        done
        echo "VPN interface ${VPN_IFACE} is up, starting Dante..."
        exec danted -D -f /run/danted.conf
    ) &
fi

cd /opt/procwatch && exec .venv/bin/python main.py
