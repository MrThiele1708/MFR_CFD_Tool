#!/usr/bin/env python3

from pathlib import Path
import os

import yaml

ROOT = Path(__file__).resolve().parents[1]


def config_path():
    value = os.environ.get(
        "CFD_CONFIG",
        "config/parameters.yaml",
    )

    path = Path(value)

    if not path.is_absolute():
        path = ROOT / path

    return path.resolve()


def load_config():
    path = config_path()

    return yaml.safe_load(
        path.read_text(encoding="utf-8")
    )


def project_path(config, key, default):
    value = config.get("project", {}).get(
        key,
        default,
    )

    path = Path(value)

    if not path.is_absolute():
        path = ROOT / path

    return path.resolve()


def case_dir(config=None):
    if config is None:
        config = load_config()

    return project_path(
        config,
        "case",
        "case",
    )


def results_dir(config=None):
    if config is None:
        config = load_config()

    return project_path(
        config,
        "results",
        "results",
    )


def manifest_path(config=None):
    if config is None:
        config = load_config()

    value = config.get(
        "geometry",
        {},
    ).get(
        "manifest",
        "config/geometryManifest.yaml",
    )

    path = Path(value)

    if not path.is_absolute():
        path = ROOT / path

    return path.resolve()


def load_manifest(config=None):
    return yaml.safe_load(
        manifest_path(config).read_text(
            encoding="utf-8"
        )
    )
