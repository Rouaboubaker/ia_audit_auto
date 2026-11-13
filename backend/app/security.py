"""Mots de passe (hachage PBKDF2 de la bibliothèque standard) et contrôle des URL soumises."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
from urllib.parse import urlparse

from .errors import ApiException

_ITER = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return salt.hex() + "$" + h.hex()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    salt_hex, hash_hex = stored.split("$")
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _ITER)
    return hmac.compare_digest(h.hex(), hash_hex)


def check_public_url(url: str) -> None:
    """Refuse les URL non http(s) et les adresses locales/privées (protection SSRF).
    En développement, ALLOW_PRIVATE=1 autorise localhost."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ApiException(400, "INVALID_URL", "L'adresse doit commencer par http:// ou https://.")
    if os.environ.get("ALLOW_PRIVATE", "0") == "1":
        return
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror:
        raise ApiException(400, "INVALID_URL", "Nom de domaine introuvable.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ApiException(400, "INVALID_URL", "Les adresses locales ou privées ne sont pas autorisées.")
