"""Cleans up an existing compose file: reorders and reformats it to the
standard layout (keeping comments), and offers each standards fix as a
separate change the user can approve or skip."""

from __future__ import annotations

import io
import ipaddress
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from . import compose_writer, networks
from .config import Config

STANDARD_NAME = "docker-compose.yml"
# The file names Docker Compose itself recognizes.
COMPOSE_NAMES = ["compose.yaml", "compose.yml", "docker-compose.yaml", STANDARD_NAME]

def find_compose_files(directory: Path) -> list[Path]:
    return [directory / name for name in COMPOSE_NAMES if (directory / name).is_file()]


def backup_path(path: Path) -> Path:
    """Date-stamped backup name that never overwrites an existing file."""
    stamp = date.today().isoformat()
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    n = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}-{n}.bak")
        n += 1
    return candidate


@dataclass
class Change:
    """One standards fix. Data changes are applied to the parsed file; text
    changes remove line ranges from the raw text before parsing."""

    description: str
    apply: Callable[[CommentedMap], None] | None = None
    remove_lines: range | None = None
    rename: bool = False


@dataclass
class Plan:
    path: Path
    text: str
    changes: list[Change] = field(default_factory=list)


def load(text: str) -> CommentedMap:
    data = compose_writer.yaml_handler().load(text)
    if not isinstance(data, CommentedMap) or not isinstance(data.get("services"), CommentedMap):
        raise ValueError("This doesn't look like a compose file (no 'services' section).")
    return data


# --- Finding changes ---------------------------------------------------------


def _service_macvlans(service: CommentedMap, cfg: Config) -> list[str]:
    nets = service.get("networks")
    if isinstance(nets, (dict, list)):
        return [n for n in nets if cfg.macvlan(n)]
    return []


def _tz_value(env) -> str | None:
    if isinstance(env, dict):
        value = env.get("TZ")
        return None if value is None else str(value)
    if isinstance(env, list):
        for entry in env:
            if isinstance(entry, str) and entry.startswith("TZ="):
                return entry[3:]
    return None


def _set_tz(service: CommentedMap, timezone: str) -> None:
    env = service.get("environment")
    if isinstance(env, dict):
        env["TZ"] = timezone
        return
    if not isinstance(env, list):
        env = CommentedSeq()
        service["environment"] = env
    entry = f"TZ={timezone}"
    for i, item in enumerate(env):
        if isinstance(item, str) and item.startswith("TZ="):
            env[i] = entry
            return
    env.append(entry)


def _service_changes(name: str, service: CommentedMap, cfg: Config) -> list[Change]:
    changes: list[Change] = []

    def svc(data: CommentedMap) -> CommentedMap:
        return data["services"][name]

    container_name = service.get("container_name")
    if container_name is None:
        changes.append(Change(
            f"[{name}] container_name: (missing) → {name}",
            lambda d: svc(d).__setitem__("container_name", name),
        ))
        container_name = name

    hostname = service.get("hostname")
    if hostname != container_name:
        changes.append(Change(
            f"[{name}] hostname: {hostname if hostname is not None else '(missing)'} → {container_name}",
            lambda d, v=container_name: svc(d).__setitem__("hostname", v),
        ))

    tz = _tz_value(service.get("environment"))
    if tz != cfg.timezone:
        changes.append(Change(
            f"[{name}] TZ: {tz if tz is not None else '(missing)'} → {cfg.timezone}",
            lambda d: _set_tz(svc(d), cfg.timezone),
        ))

    macvlans = _service_macvlans(service, cfg)
    if not macvlans:
        return changes

    if "ports" in service:
        ports = ", ".join(str(p) for p in service["ports"] or [])
        changes.append(Change(
            f"[{name}] ports: remove ({ports or 'empty'}); not used on macvlan",
            lambda d: svc(d).pop("ports", None),
        ))

    nets = service["networks"]
    if not isinstance(nets, dict):
        return changes
    for net_name in macvlans:
        macvlan = cfg.macvlan(net_name)
        net = nets.get(net_name)
        ip = net.get("ipv4_address") if isinstance(net, dict) else None
        try:
            in_subnet = ip and ipaddress.IPv4Address(str(ip)) in macvlan.network
        except ValueError:
            in_subnet = False
        if not in_subnet:
            continue
        expected = networks.mac_address(macvlan, networks.last_octet(str(ip)))
        current = net.get("mac_address")
        if current != expected:
            changes.append(Change(
                f"[{name}] {net_name} mac_address: {current or '(missing)'} → {expected}",
                lambda d, n=net_name, v=expected: svc(d)["networks"][n].__setitem__("mac_address", v),
            ))

    if "mac_address" in service:
        changes.append(Change(
            f"[{name}] mac_address: remove service-level {service['mac_address']}; "
            "it belongs under the macvlan network",
            lambda d: svc(d).pop("mac_address", None),
        ))

    return changes


_COMMENTED_PORTS = re.compile(r"^\s*#\s*ports\s*:")
_COMMENTED_ITEM = re.compile(r"^\s*#\s*-\s")
_SERVICES_LINE = re.compile(r"^services\s*:")


def _commented_ports_blocks(
    text: str, data: CommentedMap, cfg: Config
) -> list[tuple[str, Change]]:
    """Find commented-out 'ports:' blocks inside macvlan services, paired
    with the service they belong to."""
    lines = text.splitlines()
    changes: list[tuple[str, Change]] = []
    current: str | None = None
    service_indent: int | None = None
    in_services = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                in_services = bool(_SERVICES_LINE.match(line))
                current = None
                service_indent = None
            elif in_services:
                if service_indent is None:
                    service_indent = indent
                if indent == service_indent:
                    current = stripped.split(":", 1)[0].strip().strip("'\"")
        elif _COMMENTED_PORTS.match(line) and current is not None:
            end = i + 1
            while end < len(lines) and _COMMENTED_ITEM.match(lines[end]):
                end += 1
            service = data["services"].get(current)
            if isinstance(service, dict) and _service_macvlans(service, cfg):
                items = ", ".join(l.split("-", 1)[1].strip() for l in lines[i + 1:end])
                changes.append((current, Change(
                    f"[{current}] commented-out ports: remove ({items or 'empty'})",
                    remove_lines=range(i, end),
                )))
            i = end
            continue
        i += 1
    return changes


def plan(path: Path, cfg: Config) -> Plan:
    text = path.read_text()
    data = load(text)
    result = Plan(path=path, text=text)

    if "version" in data:
        result.changes.append(Change(
            f"version: remove ({data['version']}); obsolete in current Docker Compose",
            lambda d: d.pop("version", None),
        ))
    commented_ports = _commented_ports_blocks(text, data, cfg)
    for name, service in data["services"].items():
        if isinstance(service, CommentedMap):
            result.changes.extend(_service_changes(name, service, cfg))
            result.changes.extend(c for s, c in commented_ports if s == name)
    if path.name != STANDARD_NAME:
        result.changes.append(Change(f"file name: {path.name} → {STANDARD_NAME}", rename=True))
    return result


# --- Applying changes --------------------------------------------------------


def _last_leaf(node, key):
    """The (container, key) whose trailing comment follows node[key] in the file."""
    value = node[key]
    if isinstance(value, CommentedMap) and len(value):
        return _last_leaf(value, list(value.keys())[-1])
    if isinstance(value, CommentedSeq) and len(value):
        return _last_leaf(value, len(value) - 1)
    return node, key


def _rehome_comments(node) -> None:
    """ruamel attaches full-line comments to the key *before* them. Move them
    onto the key after them instead, so they travel with the key they
    describe when keys are reordered. End-of-line comments stay put."""
    if isinstance(node, CommentedSeq):
        for item in node:
            _rehome_comments(item)
        return
    if not isinstance(node, CommentedMap):
        return
    for value in node.values():
        _rehome_comments(value)
    keys = list(node.keys())
    for key, next_key in zip(keys, keys[1:]):
        holder, leaf = _last_leaf(node, key)
        entry = holder.ca.items.get(leaf)
        if not entry or len(entry) < 3 or entry[2] is None:
            continue
        inline, _, following = entry[2].value.partition("\n")
        if not following.strip():
            continue
        entry[2].value = inline + "\n"
        before = node.ca.items.setdefault(next_key, [None, None, None, None])
        before[1] = [CommentToken(following, CommentMark(0), None)] + (before[1] or [])


def _reorder(mapping: CommentedMap, first: list[str], last: list[str] = ()) -> None:
    rest = [k for k in mapping if k not in first and k not in last]
    for key in [k for k in first if k in mapping] + rest + [k for k in last if k in mapping]:
        mapping.move_to_end(key)


def _tidy(data: CommentedMap) -> None:
    _reorder(data, ["version", "name", "services"])
    for service in data["services"].values():
        if not isinstance(service, CommentedMap):
            continue
        _reorder(service, compose_writer.SERVICE_KEY_ORDER, compose_writer.SERVICE_LAST_KEYS)
        nets = service.get("networks")
        if isinstance(nets, CommentedMap):
            for net in nets.values():
                if isinstance(net, CommentedMap):
                    _reorder(net, compose_writer.NETWORK_KEY_ORDER)


def render(result: Plan, approved: list[Change]) -> str:
    """Apply the approved changes and return the tidied file text."""
    removed = {i for c in approved if c.remove_lines for i in c.remove_lines}
    text = "\n".join(l for i, l in enumerate(result.text.splitlines()) if i not in removed) + "\n"

    data = load(text)
    _rehome_comments(data)
    for change in approved:
        if change.apply:
            change.apply(data)
    _tidy(data)

    stream = io.StringIO()
    compose_writer.yaml_handler().dump(data, stream)
    return compose_writer.format_text(stream.getvalue())
