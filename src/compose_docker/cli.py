"""Entry point: orchestrates the interactive prompt flow."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ruamel.yaml.error import YAMLError

from . import cleanup, compose_writer, config, dockerhub, networks, prompts


def _read_version() -> str:
    # Installed: setup.py bundles version.json into the package.
    # Running from source: fall back to the repo-root copy.
    here = Path(__file__).resolve().parent
    for candidate in (here / "version.json", here.parents[1] / "version.json"):
        if candidate.exists():
            return json.loads(candidate.read_text())["version"]
    return "unknown"


__version__ = _read_version()


def _default_container_name(image: str) -> str:
    return image.rstrip("/").split("/")[-1]


def _backup(path: Path) -> None:
    if prompts.prompt_backup(path):
        backup = cleanup.backup_path(path)
        shutil.copy2(path, backup)
        print(f"Saved backup to {backup.name}")


def _dry_run_preview(title: str, yaml_text: str) -> None:
    print(f"\n--- {title} ---")
    print(yaml_text)
    print("-" * (len(title) + 8))
    print("Dry run: nothing written.")


def run_setup(cfg: config.Config | None) -> config.Config:
    """Ask for the per-machine settings (defaults from the current config),
    offer to import macvlans that already exist in Docker, and save."""
    print("Setup: these settings are saved on this machine and reused.\n")
    cfg = cfg or config.Config(timezone=config.system_timezone())
    cfg.timezone = prompts.prompt_timezone(cfg.timezone or config.system_timezone())
    cfg.dockerhub_account = prompts.prompt_dockerhub_account(cfg.dockerhub_account)

    try:
        found = networks.docker_macvlans()
    except networks.DockerError as exc:
        print(f"  Couldn't check Docker for existing macvlans: {exc}")
        found = []
    for net in found:
        if cfg.macvlan(net["name"]) or not prompts.prompt_import_macvlan(net):
            continue
        vlan = prompts.prompt_vlan(net["name"], networks.guess_vlan(net["name"], net["parent"]))
        cfg.macvlans.append(networks.Macvlan(vlan=vlan, **net))

    while prompts.prompt_add_another():
        cfg.macvlans.append(prompts.prompt_new_macvlan({m.name for m in cfg.macvlans}))

    print(f"Saved settings to {config.save(cfg)}\n")
    return cfg


def run(dry_run: bool = False, setup: bool = False) -> None:
    print(f"composedocker v{__version__}\n")

    cfg = config.load()
    if setup:
        run_setup(cfg)
        return
    if cfg is None:
        cfg = run_setup(None)

    existing = cleanup.find_compose_files(Path.cwd())
    if len(existing) > 1:
        names = ", ".join(p.name for p in existing)
        raise SystemExit(
            f"Found more than one compose file ({names}). "
            "Remove or rename the extras, then run again."
        )
    current = existing[0] if existing else None

    if current is not None:
        choice = prompts.prompt_existing_file(current)
        if choice == "quit":
            return
        if choice == "cleanup":
            run_cleanup(current, cfg, dry_run)
            return

    run_generate(current, cfg, dry_run)


def run_cleanup(path: Path, cfg: config.Config, dry_run: bool) -> None:
    try:
        plan = cleanup.plan(path, cfg)
    except (ValueError, YAMLError) as exc:
        raise SystemExit(f"Couldn't read {path.name}: {exc}")

    approved = []
    if plan.changes:
        print(f"\n{len(plan.changes)} change(s) to match the standards:")
        approved = [c for c in plan.changes if prompts.prompt_change(c.description)]
    else:
        print("No standards changes needed.")

    new_text = cleanup.render(plan, approved)
    target = path.with_name(cleanup.STANDARD_NAME) if any(c.rename for c in approved) else path
    if new_text == plan.text and target == path:
        print(f"{path.name} is already clean. Nothing to change.")
        return

    if dry_run:
        _dry_run_preview(f"Cleaned-up {target.name}", new_text)
        return

    message = f"Write changes to {target.name}"
    message += f" (replacing {path.name})?" if target != path else "?"
    if not prompts.prompt_confirm_write(f"Cleaned-up {target.name}", new_text, message, True):
        print("Not written.")
        return

    _backup(path)
    compose_writer.write(target, new_text)
    if target != path:
        path.unlink()
    print(f"Wrote {target}")


def _choose_macvlan(cfg: config.Config, dry_run: bool) -> networks.Macvlan:
    choice = prompts.prompt_network(cfg.macvlans)
    if choice == prompts.ADD_MACVLAN:
        choice = prompts.prompt_new_macvlan({m.name for m in cfg.macvlans})
        cfg.macvlans.append(choice)
        if dry_run:
            print(f"Dry run: {choice.name} not saved to settings.")
        else:
            print(f"Saved {choice.name} to {config.save(cfg)}")
    _ensure_docker_network(choice, dry_run)
    return choice


def _ensure_docker_network(macvlan: networks.Macvlan, dry_run: bool) -> None:
    try:
        if networks.docker_network_exists(macvlan.name):
            return
    except networks.DockerError as exc:
        print(f"  Couldn't check Docker for the {macvlan.name} network: {exc}")
        return

    command = " ".join(networks.create_command(macvlan))
    if dry_run:
        print(f"\nThe {macvlan.name} network doesn't exist in Docker on this machine.")
        print(f"Dry run: would run: {command}")
        return
    if not prompts.prompt_create_network(macvlan, command):
        print(f"  Skipped. Create {macvlan.name} before starting the container.")
        return
    try:
        networks.create_docker_network(macvlan)
    except networks.DockerError as exc:
        print(f"  Couldn't create {macvlan.name}: {exc}")
        return
    print(f"  Created {macvlan.name}.")


def run_generate(existing: Path | None, cfg: config.Config, dry_run: bool) -> None:
    image = prompts.prompt_image(cfg.dockerhub_account)
    tag = prompts.prompt_tag(image)

    container_name = prompts.prompt_container_name(_default_container_name(image))

    print(f"Checking {image}:{tag} for declared volumes...")
    try:
        volume_paths = dockerhub.get_declared_volumes(image, tag)
    except dockerhub.DockerHubError as exc:
        print(f"  Warning: {exc}\n  Skipping automatic volume detection.")
        volume_paths = []

    if volume_paths:
        print(f"  Found declared volume path(s): {', '.join(volume_paths)}")
    else:
        print("  No declared volumes found.")

    restart = prompts.prompt_restart()
    macvlan = _choose_macvlan(cfg, dry_run)
    ipv4_address = prompts.prompt_ip(macvlan)

    compose = compose_writer.build_compose(
        image=image,
        tag=tag,
        container_name=container_name,
        volume_paths=volume_paths,
        restart=restart,
        network_name=macvlan.name,
        ipv4_address=ipv4_address,
        mac_address=networks.mac_address(macvlan, networks.last_octet(ipv4_address)),
        timezone=cfg.timezone,
    )
    yaml_text = compose_writer.to_yaml(compose)

    target = Path.cwd() / cleanup.STANDARD_NAME
    if dry_run:
        _dry_run_preview(f"Generated {target.name}", yaml_text)
        return

    if existing is None:
        message = f"Write to {target.name}?"
    elif existing == target:
        message = f"Overwrite existing {target.name}?"
    else:
        message = f"Write {target.name} and remove existing {existing.name}?"
    if not prompts.prompt_confirm_write(
        f"Generated {target.name}", yaml_text, message, existing is None
    ):
        print("Not written.")
        return

    if existing is not None:
        _backup(existing)
    compose_writer.write(target, yaml_text)
    if existing is not None and existing != target:
        existing.unlink()
    print(f"Wrote {target}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="composedocker", description=__doc__)
    parser.add_argument(
        "-v", "--version", action="version", version=f"composedocker v{__version__}"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the resulting compose file without writing anything",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="change the saved timezone, Docker Hub account and macvlan networks",
    )
    args = parser.parse_args()

    try:
        run(dry_run=args.dry_run, setup=args.setup)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
