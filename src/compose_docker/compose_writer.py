"""Builds the compose dict from collected answers and serializes it to YAML."""

from __future__ import annotations

import io
import re
from pathlib import Path

from ruamel.yaml import YAML

TIMEZONE = "America/Indiana/Indianapolis"

# Standard key order within a service (see GitHub issue #5). Keys not listed
# here keep their original relative order and go between "networks" and
# "restart", so "restart" is always last.
SERVICE_KEY_ORDER = [
    "image",
    "container_name",
    "hostname",
    "environment",
    "volumes",
    "ports",
    "networks",
]
SERVICE_LAST_KEYS = ["restart"]
NETWORK_KEY_ORDER = ["ipv4_address", "mac_address"]


def yaml_handler() -> YAML:
    """Round-trip YAML handler: keeps comments and quoting, and indents list
    items under their key, matching typical hand-written compose files."""
    handler = YAML()
    handler.preserve_quotes = True
    handler.width = 4096
    handler.indent(mapping=2, sequence=4, offset=2)
    return handler


def volume_mount(container_path: str) -> str:
    """Turn a declared container path into a bind mount, e.g.
    '/var/lib/postgresql/data' -> './postgresql-data:/var/lib/postgresql/data'
    using the last path segment (plus its parent if the segment alone is
    too generic, e.g. 'data') as the host-side folder name.
    """
    segments = [s for s in container_path.split("/") if s]
    if not segments:
        host_dir = "data"
    elif segments[-1] in {"data", "config", "conf"} and len(segments) > 1:
        host_dir = f"{segments[-2]}-{segments[-1]}"
    else:
        host_dir = segments[-1]
    return f"./{host_dir}:{container_path}"


def build_compose(
    *,
    image: str,
    tag: str,
    container_name: str,
    volume_paths: list[str],
    restart: str,
    network_name: str,
    ipv4_address: str,
    mac_address: str,
) -> dict:
    service: dict = {
        "image": f"{image}:{tag}",
        "container_name": container_name,
        "hostname": container_name,
        "environment": [f"TZ={TIMEZONE}"],
    }

    if volume_paths:
        service["volumes"] = [volume_mount(p) for p in volume_paths]

    service["networks"] = {
        network_name: {"ipv4_address": ipv4_address, "mac_address": mac_address}
    }
    service["restart"] = restart

    return {
        "services": {container_name: service},
        "networks": {network_name: {"external": True}},
    }


_KEY_LINE = re.compile(r"^\s*[^\s#-][^:]*:(\s|$)")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def format_text(text: str) -> str:
    """Normalize blank lines: none inside a service, and one before each
    top-level section and between services. A comment directly above one of
    those keys, at the same indent, stays attached to it."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]

    # Keys that get a blank line above them: every top-level key except the
    # first, and every service except the first.
    separated: set[int] = set()
    seen_top_level = False
    in_services = False
    service_indent: int | None = None
    for i, line in enumerate(lines):
        if _is_comment(line) or not _KEY_LINE.match(line):
            continue
        indent = _indent(line)
        if indent == 0:
            if seen_top_level:
                separated.add(i)
            seen_top_level = True
            in_services = line.startswith("services:")
            service_indent = None
        elif in_services:
            if service_indent is None:
                service_indent = indent
            elif indent == service_indent:
                separated.add(i)

    out: list[str] = []
    for i, line in enumerate(lines):
        if i in separated:
            j = len(out)
            while j > 0 and _is_comment(out[j - 1]) and _indent(out[j - 1]) == _indent(line):
                j -= 1
            out.insert(j, "")
        out.append(line)
    return "\n".join(out) + "\n"


def to_yaml(compose) -> str:
    stream = io.StringIO()
    yaml_handler().dump(compose, stream)
    return format_text(stream.getvalue())


def write(path: Path, yaml_text: str) -> None:
    path.write_text(yaml_text)
