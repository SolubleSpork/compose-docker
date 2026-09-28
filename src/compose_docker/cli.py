"""Entry point: orchestrates the interactive prompt flow."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ruamel.yaml.error import YAMLError

from . import cleanup, compose_writer, dockerhub, prompts


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


def run(dry_run: bool = False) -> None:
    print(f"composedocker v{__version__}\n")

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
            run_cleanup(current, dry_run)
            return

    run_generate(current, dry_run)


def run_cleanup(path: Path, dry_run: bool) -> None:
    try:
        plan = cleanup.plan(path)
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


def run_generate(existing: Path | None, dry_run: bool) -> None:
    image = prompts.prompt_image()
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
    network_name, ipv4_address, mac_address = prompts.prompt_network()

    compose = compose_writer.build_compose(
        image=image,
        tag=tag,
        container_name=container_name,
        volume_paths=volume_paths,
        restart=restart,
        network_name=network_name,
        ipv4_address=ipv4_address,
        mac_address=mac_address,
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
    args = parser.parse_args()

    try:
        run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
