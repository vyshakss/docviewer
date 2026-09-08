# app/net.py
from fastapi import Request


def client_ip(request: Request) -> str:
    # Cloudflare Tunnel proxies over localhost, so request.client.host is the
    # tunnel connector's address for every visitor, not the real client. When
    # fronted by Cloudflare, trust its CF-Connecting-IP header instead — it's
    # only spoofable by something that can reach the app directly (LAN or
    # cloudflared itself), not by internet clients, as long as port 8000 is
    # never forwarded straight to the internet.
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    return request.client.host if request.client else "unknown"
