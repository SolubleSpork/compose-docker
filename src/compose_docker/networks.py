"""Hardcoded macvlan network definitions.

These networks are assumed to already exist on the Docker host
(created out-of-band via `docker network create -d macvlan ...`) —
this tool only references them, never defines them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Macvlan:
    name: str
    vlan: int
    subnet_prefix: str  # e.g. "192.168.20" — first three octets


MACVLANS: list[Macvlan] = [
    Macvlan(name="20-prod", vlan=20, subnet_prefix="192.168.20"),
    Macvlan(name="30-sandbox", vlan=30, subnet_prefix="192.168.30"),
]


def static_ip(macvlan: Macvlan, last_octet: int) -> str:
    if not 0 <= last_octet <= 255:
        raise ValueError("Last octet must be between 0 and 255")
    return f"{macvlan.subnet_prefix}.{last_octet}"
