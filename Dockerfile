FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl \
    git \
    vim \
    htop \
    jq \
    bind9-dnsutils \
    traceroute \
    iputils-tracepath \
    inetutils-traceroute \
    iptables \
    net-tools \
    iputils-ping \
    iproute2 \
    nmap \
    tcpdump \
    tinyproxy \
    screen \
    dnsmasq \
    dante-server \
    openfortivpn \
    expect \
    ca-certificates \
    gnupg \
    python3 \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# snx-rs (CheckPoint VPN)
RUN curl -fsSL -o /etc/apt/sources.list.d/snx-rs.sources \
    https://ancwrd1.github.io/snx-rs/snx-rs.sources \
    && apt-get update \
    && apt-get install -y snx-rs \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI (for FortiClient — uses host daemon via mounted socket)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
    https://download.docker.com/linux/ubuntu noble stable" \
    > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# ProcWatch — VPN process watchdog
COPY procwatch/requirements.txt /opt/procwatch/requirements.txt
RUN python3 -m venv /opt/procwatch/.venv \
    && /opt/procwatch/.venv/bin/pip install --no-cache-dir -r /opt/procwatch/requirements.txt
COPY procwatch/main.py procwatch/manager.py procwatch/config.py /opt/procwatch/
COPY procwatch/templates/ /opt/procwatch/templates/

RUN mkdir -p /root/.config/snx-rs

# VPN control scripts
COPY scripts/ /opt/vpn/
RUN chmod +x /opt/vpn/*.sh

# static configs — all mountable from host to override
COPY config/dnsmasq.conf /config/dnsmasq.conf
COPY config/danted.conf /config/danted.conf
COPY config/procwatch-checkpoint.yaml /config/procwatch-checkpoint.yaml
COPY config/procwatch-forticlient.yaml /config/procwatch-forticlient.yaml
COPY config/proxy.pac /config/proxy.pac
COPY config/tinyproxy.conf /config/tinyproxy.conf

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080 1080 8888
# 8080 - proxy.pac
# 1080 - dante
# 8888 - tinyproxy

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
