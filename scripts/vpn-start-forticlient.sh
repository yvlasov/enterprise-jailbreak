#!/bin/bash
set -e

OUTPUT=$(docker run --rm \
    -e FORTI_VPN_HOST="${FORTI_VPN_HOST}" \
    -e FORTI_VPN_USER="${FORTI_VPN_USER}" \
    -e FORTI_VPN_PASSWORD="${FORTI_VPN_PASSWORD}" \
    yvlasov/forti-cookie)

COOKIE=$(echo "$OUTPUT" | sed -n 's/^FORTI_VPN_COOKIE=//p')
[ -n "$COOKIE" ] || { echo "ERROR: cookie not found in forti-cookie output"; echo "$OUTPUT"; exit 1; }

exec openfortivpn "${FORTI_VPN_HOST}:${FORTI_VPN_PORT:-443}" \
    --username="${FORTI_VPN_USER}" \
    --cookie="${COOKIE}" \
    ${FORTI_VPN_TRUSTED_CERT:+--trusted-cert="${FORTI_VPN_TRUSTED_CERT}"}
