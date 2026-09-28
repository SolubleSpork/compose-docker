"""Builds the compose dict from collected answers and serializes it to YAML."""

from __future__ import annotations

from pathlib import Path

import yaml


class _IndentedDumper(yaml.Dumper):
    """Indents list items under their key, matching typical hand-written compose files."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


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
) -> dict:
    service: dict = {
        "image": f"{image}:{tag}",
        "container_name": container_name,
        "hostname": container_name,
        "environment": ["TZ=America/Indiana/Indianapolis"],
    }

    if volume_paths:
        service["volumes"] = [volume_mount(p) for p in volume_paths]

    service["networks"] = {network_name: {"ipv4_address": ipv4_address}}
    service["restart"] = restart

    return {
        "services": {container_name: service},
        "networks": {network_name: {"external": True}},
    }


def to_yaml(compose: dict) -> str:
    # Dump each top-level section separately so they can be separated by a
    # blank line (e.g. services, then the external networks definition).
    return "\n".join(
        yaml.dump(
            {key: value},
            Dumper=_IndentedDumper,
            sort_keys=False,
            default_flow_style=False,
        )
        for key, value in compose.items()
    )


def write(path: Path, yaml_text: str) -> None:
    path.write_text(yaml_text)
