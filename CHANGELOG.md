# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Initial implementation: interactive CLI that generates a `docker-compose.yml` via live Docker Hub image search, automatic bind-mount detection from image-declared `VOLUME` paths, restart policy selection, and macvlan network/static-IP assignment.

### Changed
- Generated compose files now have a blank line between top-level sections.

### Fixed
- Package version now comes from `version.json`, so it can no longer drift from the version the tool reports.
