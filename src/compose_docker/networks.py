"""Macvlan network definitions, stored in the user's local config file, and
the Docker commands to check for and create them on this machine."""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Macvlan:
    name: str
    vlan: int
    subnet: str  # CIDR, e.g. "192.168.20.0/24"
    gateway: str
    parent: str  # host interface, e.g. "eth0" or "eth0.20"

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(self.subnet, strict=False)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Macvlan:
        return cls(
            name=str(data["name"]),
            vlan=int(data["vlan"]),
            subnet=str(data["subnet"]),
            gateway=str(data["gateway"]),
            parent=str(data["parent"]),
        )


def last_octet(ip: str) -> int:
    return int(ip.rsplit(".", 1)[1])


def mac_address(macvlan: Macvlan, ip_last_octet: int) -> str:
    """Standard MAC for a macvlan container: 02:VV:VV:00:0I:II, where the
    VLAN and the IP's last octet are each written in decimal, zero-padded to
    four digits and split across two MAC octets.
    e.g. VLAN 20, x.x.x.111 -> 02:00:20:00:01:11
    """
    vlan = f"{macvlan.vlan:04d}"
    octet = f"{ip_last_octet:04d}"
    return f"02:{vlan[:2]}:{vlan[2:]}:00:{octet[:2]}:{octet[2:]}"


def guess_vlan(name: str, parent: str) -> int | None:
    """VLAN from a tagged parent interface (eth0.20) or a leading number in
    the network name (20-prod)."""
    for pattern, text in ((r"\.(\d+)$", parent), (r"^(\d+)", name)):
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


# --- Docker ------------------------------------------------------------------


class DockerError(Exception):
    pass


def _docker(*args: str) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, check=True, timeout=30
        )
    except FileNotFoundError as exc:
        raise DockerError("docker isn't installed or isn't on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise DockerError(exc.stderr.strip() or str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerError("docker didn't respond") from exc
    return result.stdout


def docker_network_exists(name: str) -> bool:
    names = _docker("network", "ls", "--format", "{{.Name}}").split()
    return name in names


def docker_macvlans() -> list[dict]:
    """Existing macvlan networks in Docker, as partial Macvlan fields
    (everything but the VLAN, which Docker doesn't record)."""
    names = _docker("network", "ls", "--filter", "driver=macvlan", "--format", "{{.Name}}").split()
    found = []
    for name in names:
        info = json.loads(_docker("network", "inspect", name))[0]
        ipam = (info.get("IPAM") or {}).get("Config") or [{}]
        found.append({
            "name": name,
            "subnet": ipam[0].get("Subnet", ""),
            "gateway": ipam[0].get("Gateway", ""),
            "parent": (info.get("Options") or {}).get("parent", ""),
        })
    return found


def create_command(macvlan: Macvlan) -> list[str]:
    return [
        "docker", "network", "create", "-d", "macvlan",
        "--subnet", macvlan.subnet,
        "--gateway", macvlan.gateway,
        "-o", f"parent={macvlan.parent}",
        macvlan.name,
    ]


def create_docker_network(macvlan: Macvlan) -> None:
    _docker(*create_command(macvlan)[1:])
