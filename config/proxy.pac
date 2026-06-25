function FindProxyForURL(url, host) {
    // Direct connection for local addresses
    if (isPlainHostName(host) || isInNet(host, "127.0.0.0", "255.0.0.0")) {
        return "DIRECT";
    }

    // Route everything else through the SOCKS5 proxy
    return "SOCKS5 localhost:1080; DIRECT";
}
