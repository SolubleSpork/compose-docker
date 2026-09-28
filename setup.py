"""Reads the package version from version.json, the single source of truth,
and bundles that file into the package so the CLI can report the exact
string (including any -beta suffix) at runtime."""

import json
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).parent
VERSION = json.loads((ROOT / "version.json").read_text())["version"]


class BuildPyWithVersion(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / "compose_docker" / "version.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "version.json", target)


setup(version=VERSION, cmdclass={"build_py": BuildPyWithVersion})
