"""Entry point: orchestrates the interactive prompt flow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import compose_writer, dockerhub, prompts

# Kept in sync with version.json at release time — a pip package has no
# build step to read version.json at runtime the way the Vite webapps do.
__version__ = "0.1.0-beta"


def _default_container_name(image: str) -> str:
    return image.rstrip("/").split("/")[-1]


def run() -> None:
    print(f"composedocker v{__version__}\n")

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
    network_name, ipv4_address = prompts.prompt_network()

    compose = compose_writer.build_compose(
        image=image,
        tag=tag,
        container_name=container_name,
        volume_paths=volume_paths,
        restart=restart,
        network_name=network_name,
        ipv4_address=ipv4_address,
    )
    yaml_text = compose_writer.to_yaml(compose)

    target = Path.cwd() / "docker-compose.yml"
    if not prompts.prompt_confirm_write(target, yaml_text):
        print("Not written.")
        return

    compose_writer.write(target, yaml_text)
    print(f"Wrote {target}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="composedocker", description=__doc__)
    parser.add_argument(
        "-v", "--version", action="version", version=f"composedocker v{__version__}"
    )
    parser.parse_args()

    try:
        run()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
