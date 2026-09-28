# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Per-machine settings file (timezone, Docker Hub account, macvlan networks) created by a first-run setup, editable with `--setup`. Existing macvlans are detected in Docker and offered for import; new ones can be added from the network picker, and a missing macvlan can be created in Docker.
- `--dry-run` flag: shows the resulting compose file without writing, backing up or renaming anything.
- Clean up an existing compose file in the current folder: standard key order and formatting (comments kept), plus individually approved standards fixes and an optional date-stamped backup.
- Containers on a macvlan now get a fixed MAC address (`02:VV:VV:00:0I:II`) derived from the VLAN and IP.
- Initial implementation: interactive CLI that generates a `docker-compose.yml` via live Docker Hub image search, automatic bind-mount detection from image-declared `VOLUME` paths, restart policy selection, and macvlan network/static-IP assignment.

### Changed
- Timezone, Docker Hub account and macvlan networks are no longer hardcoded; they come from the settings file.
- Generated compose files now have a blank line between top-level sections.
- Switched YAML library from PyYAML to ruamel.yaml so comments survive a cleanup.

### Fixed
- Package version now comes from `version.json`, so it can no longer drift from the version the tool reports.
