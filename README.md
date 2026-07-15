# compose-docker

Interactive CLI that generates a `docker-compose.yml` matching a fixed set of personal deployment standards — no more hand-writing the same container/hostname/volume/network boilerplate for every project.

## Features
- Live search-as-you-type against Docker Hub for the image to use
- Automatic tag defaulting to `latest`, with an optional fetch-and-pick from the image's real tag list
- `container_name` defaulted from the image name (editable), `hostname` always mirrored from it
- Bind-mount volumes auto-detected from the image's declared `VOLUME` paths — no guessing container-side paths
- Restart policy selection (defaults to `unless-stopped`)
- macvlan network assignment: pick a VLAN, enter the last IP octet, get a static `ipv4_address` wired up automatically

## Requirements
- Python 3.10+
- `pip`

## Installation / Quick Start
```
curl -fsSL https://raw.githubusercontent.com/SolubleSpork/compose-docker/main/install.sh | bash
```

That installs a `composedocker` command onto your `PATH` (via `pip3 install --user`, so nothing needs elevated/system-wide access). Run the same command again any time to upgrade to the latest version on `main`.

## Configuration
None — all inputs are gathered interactively when you run the tool.

## Usage
```
cd ~/docker/some-project
composedocker
```

Walks through image selection, tag, container name, volumes, restart policy, and network in order, then shows a preview of the generated `docker-compose.yml` before writing it to the current directory (asks for confirmation if a file already exists there).

```
composedocker --version
```

## Development & Releases
`main` is both the working branch and the source the install command above pulls from — there is no separate release branch. Changes only reach users once they're pushed to `main`, so all work stays local and is tested with `pip install -e .` until it's confirmed working.

## License
MIT
