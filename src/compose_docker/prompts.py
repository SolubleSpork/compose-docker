"""Interactive prompts for each compose field."""

from __future__ import annotations

from pathlib import Path

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

    def __init__(self) -> None:
        self._search_cache: dict[str, list[dict]] = {}
        self._namespace_repos: list[dict] | None = None

    def _namespace_matches(self, text: str) -> list[dict]:
        if self._namespace_repos is None:
            try:
                self._namespace_repos = dockerhub.list_namespace_repos()
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
            repo_name = f"{dockerhub.PERSONAL_NAMESPACE}/{name}"
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


def prompt_image() -> str:
    image = questionary.text(
        "Container image:",
        completer=DockerHubCompleter(),
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


def _validate_octet(value: str) -> bool | str:
    if not value.isdigit() or not 0 <= int(value) <= 255:
        return "Enter a number between 0 and 255"
    return True


def prompt_network() -> tuple[str, str, str]:
    choices = [
        questionary.Choice(title=f"{m.name}  ({m.subnet_prefix}.0/24)", value=m)
        for m in networks.MACVLANS
    ]
    macvlan = questionary.select("Macvlan network:", choices=choices).ask()
    if macvlan is None:
        raise SystemExit("Aborted.")

    octet = questionary.text(
        f"Last IP octet ({macvlan.subnet_prefix}.__):", validate=_validate_octet
    ).ask()
    if octet is None:
        raise SystemExit("Aborted.")

    ip = networks.static_ip(macvlan, int(octet))
    mac = networks.mac_address(macvlan, int(octet))
    return macvlan.name, ip, mac


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
