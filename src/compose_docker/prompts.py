"""Interactive prompts for each compose field."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import questionary
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from . import dockerhub, networks

RESTART_CHOICES = ["unless-stopped", "always", "on-failure", "no"]


class DockerHubCompleter(Completer):
    """Live-searches Docker Hub as the user types.

    Your own namespace's repos are matched locally (substring match, no API
    tokenization involved) and always shown first, since Docker Hub's search
    API tokenizes on hyphens and won't reliably surface a hyphenated name like
    "pto-tracker" while it's still partially typed. General Docker Hub search
    results follow, in raw relevance order, for everything else.
    """

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._search_cache: dict[str, list[dict]] = {}
        self._namespace_repos: list[dict] | None = None if namespace else []

    def _namespace_matches(self, text: str) -> list[dict]:
        if self._namespace_repos is None:
            try:
                self._namespace_repos = dockerhub.list_namespace_repos(self._namespace)
            except dockerhub.DockerHubError:
                self._namespace_repos = []
        needle = text.lower()
        return [r for r in self._namespace_repos if needle in r.get("name", "").lower()]

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor.strip()
        if not text:
            return

        shown: set[str] = set()

        for result in self._namespace_matches(text):
            name = result.get("name", "")
            if not name:
                continue
            repo_name = f"{self._namespace}/{name}"
            shown.add(repo_name)
            stars = result.get("star_count", 0)
            display = f"{repo_name}  ★{stars}"
            yield Completion(repo_name, start_position=-len(text), display=display)

        if len(text) < 2:
            return

        if text not in self._search_cache:
            try:
                self._search_cache[text] = dockerhub.search_repositories(text)
            except dockerhub.DockerHubError:
                self._search_cache[text] = []
        for result in self._search_cache[text]:
            name = result.get("repo_name", "")
            if not name or name in shown:
                continue
            tag = " [official]" if result.get("is_official") else ""
            stars = result.get("star_count", 0)
            display = f"{name}{tag}  ★{stars}"
            yield Completion(name, start_position=-len(text), display=display)


def prompt_image(dockerhub_account: str) -> str:
    image = questionary.text(
        "Container image:",
        completer=DockerHubCompleter(dockerhub_account),
    ).ask()
    if not image or not image.strip():
        raise SystemExit("No image selected — aborting.")
    return image.strip()


def prompt_tag(repo: str) -> str:
    use_latest = questionary.confirm(f"Use tag 'latest' for {repo}?", default=True).ask()
    if use_latest is None:
        raise SystemExit("Aborted.")
    if use_latest:
        return "latest"

    print(f"Fetching available tags for {repo}...")
    try:
        token = dockerhub.get_anon_token(repo)
        tags = dockerhub.list_tags(repo, token)
    except dockerhub.DockerHubError as exc:
        print(f"  Warning: {exc}\n  Falling back to manual tag entry.")
        tags = []

    if tags:
        tag = questionary.autocomplete(f"Tag for {repo}:", choices=tags).ask()
    else:
        tag = questionary.text(f"Tag for {repo}:").ask()

    if not tag or not tag.strip():
        raise SystemExit("No tag selected — aborting.")
    return tag.strip()


def prompt_container_name(default: str) -> str:
    name = questionary.text("Container name:", default=default).ask()
    if not name or not name.strip():
        raise SystemExit("Container name is required — aborting.")
    return name.strip()


def prompt_restart() -> str:
    restart = questionary.select(
        "Restart policy:", choices=RESTART_CHOICES, default="unless-stopped"
    ).ask()
    if not restart:
        raise SystemExit("Aborted.")
    return restart


def _ask(question):
    answer = question.ask()
    if answer is None:
        raise SystemExit("Aborted.")
    return answer


ADD_MACVLAN = "__add__"


def prompt_network(macvlans: list[networks.Macvlan]) -> networks.Macvlan | str:
    """Returns the chosen macvlan, or ADD_MACVLAN to define a new one."""
    choices = [
        questionary.Choice(title=f"{m.name}  ({m.subnet})", value=m) for m in macvlans
    ]
    choices.append(questionary.Choice(title="Add a new macvlan…", value=ADD_MACVLAN))
    return _ask(questionary.select("Macvlan network:", choices=choices))


def prompt_ip(macvlan: networks.Macvlan) -> str:
    net = macvlan.network
    hosts = f"{net.network_address + 1} to {net.broadcast_address - 1}"

    def parse(value: str) -> ipaddress.IPv4Address | None:
        value = value.strip()
        if net.prefixlen == 24 and value.isdigit():
            value = f"{str(net.network_address).rsplit('.', 1)[0]}.{value}"
        try:
            ip = ipaddress.IPv4Address(value)
        except ValueError:
            return None
        usable = ip in net and ip not in (net.network_address, net.broadcast_address)
        return ip if usable else None

    if net.prefixlen == 24:
        prefix = str(net.network_address).rsplit(".", 1)[0]
        message = f"Last IP octet ({prefix}.__):"
    else:
        message = f"IP address ({hosts}):"
    answer = _ask(questionary.text(
        message, validate=lambda v: parse(v) is not None or f"Enter an address from {hosts}"
    ))
    return str(parse(answer))


def prompt_create_network(macvlan: networks.Macvlan, command: str) -> bool:
    print(f"\nThe {macvlan.name} network doesn't exist in Docker on this machine.")
    print(f"  {command}")
    return _ask(questionary.confirm("Create it now?", default=True))


# --- Setup -------------------------------------------------------------------


def _valid_timezone(value: str) -> bool | str:
    try:
        ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return "Not a known timezone (e.g. America/Chicago)"
    return True


def prompt_timezone(default: str) -> str:
    return _ask(questionary.text(
        "Timezone for containers (TZ):", default=default, validate=_valid_timezone
    )).strip()


def prompt_dockerhub_account(default: str) -> str:
    return _ask(questionary.text(
        "Your Docker Hub account (its images are listed first in search; blank for none):",
        default=default,
    )).strip()


def prompt_import_macvlan(found: dict) -> bool:
    return _ask(questionary.confirm(
        f"Found macvlan {found['name']} in Docker "
        f"({found['subnet']}, gateway {found['gateway']}, parent {found['parent']}). Import it?",
        default=True,
    ))


def _valid_vlan(value: str) -> bool | str:
    if value.strip().isdigit() and 1 <= int(value) <= 4094:
        return True
    return "Enter a VLAN number from 1 to 4094"


def prompt_vlan(name: str, default: int | None) -> int:
    answer = _ask(questionary.text(
        f"VLAN number for {name} (used in its containers' MAC addresses):",
        default="" if default is None else str(default),
        validate=_valid_vlan,
    ))
    return int(answer)


def prompt_add_another() -> bool:
    return _ask(questionary.confirm("Add a macvlan by hand?", default=False))


def prompt_new_macvlan(taken: set[str]) -> networks.Macvlan:
    def valid_name(value: str) -> bool | str:
        value = value.strip()
        if not value:
            return "Name is required"
        return value not in taken or "That name is already configured"

    def valid_subnet(value: str) -> bool | str:
        try:
            ipaddress.IPv4Network(value.strip(), strict=False)
        except ValueError:
            return "Enter a subnet like 192.168.20.0/24"
        return "/" in value or "Include the prefix length, e.g. /24"

    name = _ask(questionary.text("Network name (e.g. 20-prod):", validate=valid_name)).strip()
    vlan = prompt_vlan(name, networks.guess_vlan(name, ""))
    subnet_text = _ask(questionary.text("Subnet (e.g. 192.168.20.0/24):", validate=valid_subnet))
    subnet = ipaddress.IPv4Network(subnet_text.strip(), strict=False)

    def valid_gateway(value: str) -> bool | str:
        try:
            return ipaddress.IPv4Address(value.strip()) in subnet or f"Must be inside {subnet}"
        except ValueError:
            return "Enter an IP address"

    gateway = _ask(questionary.text(
        "Gateway:", default=str(subnet.network_address + 1), validate=valid_gateway
    )).strip()
    parent = _ask(questionary.text(
        "Parent interface on the Docker host (e.g. eth0 or eth0.20):",
        validate=lambda v: bool(v.strip()) or "Parent interface is required",
    )).strip()
    return networks.Macvlan(name=name, vlan=vlan, subnet=str(subnet), gateway=gateway, parent=parent)


def prompt_existing_file(path: Path) -> str:
    choice = questionary.select(
        f"Found {path.name} in this folder. What do you want to do?",
        choices=[
            questionary.Choice("Clean up existing file", value="cleanup"),
            questionary.Choice("Start fresh", value="fresh"),
            questionary.Choice("Quit", value="quit"),
        ],
    ).ask()
    return choice or "quit"


def prompt_change(description: str) -> bool:
    answer = questionary.confirm(f"{description}  — apply?", default=True).ask()
    if answer is None:
        raise SystemExit("Aborted.")
    return answer


def prompt_backup(path: Path) -> bool:
    answer = questionary.confirm(f"Save a backup of {path.name} first?", default=True).ask()
    if answer is None:
        raise SystemExit("Aborted.")
    return answer


def prompt_confirm_write(title: str, yaml_text: str, message: str, default: bool) -> bool:
    print(f"\n--- {title} ---")
    print(yaml_text)
    print("-" * (len(title) + 8))
    return bool(questionary.confirm(message, default=default).ask())
