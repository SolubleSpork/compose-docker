# compose-docker

Interactive CLI that generates a `docker-compose.yml` matching a fixed set of personal deployment standards — no more hand-writing the same container/hostname/volume/network boilerplate for every project.

## Features
- Live search-as-you-type against Docker Hub for the image to use
- Automatic tag defaulting to `latest`, with an optional fetch-and-pick from the image's real tag list
- `container_name` defaulted from the image name (editable), `hostname` always mirrored from it
- Bind-mount volumes auto-detected from the image's declared `VOLUME` paths — no guessing container-side paths
- Restart policy selection (defaults to `unless-stopped`)
- macvlan network assignment: pick one of your macvlans, enter the IP, get a static `ipv4_address` and matching `mac_address` (`02:VV:VV:00:0I:II`, from the VLAN and the IP's last octet) wired up automatically; missing macvlans can be created in Docker for you
- Cleanup of an existing compose file: reorders and reformats it to the standard layout (comments kept), and offers each standards fix (timezone, hostname, MAC address, unused ports, file name, etc.) as a separate change you approve or skip

## Requirements
- Python 3.10+ (included with current Ubuntu/Debian). No pip or other packages needed.

## Installation / Quick Start
```
curl -sL solublespork.github.io/compose-docker | bash
```

That installs a `composedocker` command into `~/.local/bin`, with the tool and its libraries in `~/.local/share/compose-docker`. It's for your user only, so no `sudo` is needed. The installer uses only Python's standard library, and checks every downloaded library against a pinned checksum. Run the same command again any time to upgrade to the latest version on `main`.

## Configuration
The first time you run `composedocker`, it asks for a few settings and saves them on that machine at `~/.config/compose-docker/config.yml` (or under `$XDG_CONFIG_HOME` if set). Nothing personal is built into the tool.

| Setting | What it's for |
|---|---|
| `timezone` | `TZ` value given to every container (defaults to the machine's timezone) |
| `dockerhub_account` | Your Docker Hub account; its images are listed first in the image search. Optional. |
| `macvlans` | Your macvlan networks: `name`, `vlan`, `subnet`, `gateway`, `parent` (host interface) |

During setup, macvlan networks that already exist in Docker are detected and offered for import. More can be added any time from the network picker ("Add a new macvlan…"). If a chosen macvlan doesn't exist in Docker yet, the tool offers to create it.

Change settings later with `composedocker --setup`, or edit the file directly.

## Usage
```
cd ~/docker/some-project
composedocker
```

Walks through image selection, tag, container name, volumes, restart policy, and network in order, then shows a preview of the generated `docker-compose.yml` before writing it to the current directory.

If the folder already has a compose file (`docker-compose.yml`, `docker-compose.yaml`, `compose.yml` or `compose.yaml`), you're asked whether to clean it up, start fresh, or quit. Cleaning up lists each change needed to match the standards, one at a time, so you can keep deliberate deviations. You're then shown a preview of the result. Before anything is overwritten, you can save a date-stamped backup (e.g. `docker-compose.yml.2026-09-28.bak`), which never replaces an existing `.bak` file.

```
composedocker --dry-run    # show the result without writing anything
composedocker --setup      # change saved settings and macvlans
composedocker --version
```

## Development & Releases
`main` is both the working branch and the source the install command above pulls from (the install script is `index.html`, served by GitHub Pages) — there is no separate release branch. Changes only reach users once they're pushed to `main`, so all work stays local and is tested there until it's confirmed working.

## License
MIT
