"""Per-machine settings (timezone, Docker Hub account, macvlan networks),
saved outside the repo so no personal details are baked into the tool."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .compose_writer import yaml_handler
from .networks import Macvlan


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "compose-docker" / "config.yml"


@dataclass
class Config:
    timezone: str
    dockerhub_account: str = ""
    macvlans: list[Macvlan] = field(default_factory=list)

    def macvlan(self, name: str) -> Macvlan | None:
        return next((m for m in self.macvlans if m.name == name), None)


def load() -> Config | None:
    path = config_path()
    if not path.is_file():
        return None
    data = yaml_handler().load(path.read_text()) or {}
    return Config(
        timezone=str(data.get("timezone", "")),
        dockerhub_account=str(data.get("dockerhub_account") or ""),
        macvlans=[Macvlan.from_dict(m) for m in data.get("macvlans") or []],
    )


def save(cfg: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "timezone": cfg.timezone,
        "dockerhub_account": cfg.dockerhub_account,
        "macvlans": [m.to_dict() for m in cfg.macvlans],
    }
    with path.open("w") as f:
        f.write("# compose-docker settings. Edit freely, or run: composedocker --setup\n")
        yaml_handler().dump(data, f)
    return path


def system_timezone() -> str:
    """Best guess at this machine's timezone, used as the setup default."""
    try:
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        pass
    try:
        return str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"
