#!/usr/bin/env python3
"""Validate release tag provenance and classify the release safely."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence


class ReleaseValidationError(RuntimeError):
    """The requested tag is malformed, mismatched, or stale."""


_CORE_PATTERN = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_TAG_RE = re.compile(rf"^v(?P<base>{_CORE_PATTERN})(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")
_CORE_RE = re.compile(rf"^{_CORE_PATTERN}$")


@dataclass(frozen=True)
class ReleaseMetadata:
    tag_version: str
    base_version: str
    prerelease: bool


def validate_release(
    *, tag_name: str, file_version: str, main_version: str
) -> ReleaseMetadata:
    """Require a strict, current-main release tag matching committed VERSION."""
    match = _TAG_RE.fullmatch(tag_name)
    prerelease = match.group("pre") if match else None
    if (
        match is None
        or (prerelease is not None and any(
            part.isdigit() and len(part) > 1 and part.startswith("0")
            for part in prerelease.split(".")
        ))
    ):
        raise ReleaseValidationError(
            f"tag {tag_name!r} is not a strict release SemVer (vX.Y.Z or vX.Y.Z-pre)"
        )

    base_version = match.group("base")
    tag_version = tag_name[1:]
    if not _CORE_RE.fullmatch(file_version) or tag_version not in {
        file_version,
        f"{file_version}-{prerelease}" if prerelease else file_version,
    }:
        raise ReleaseValidationError(
            f"tag {tag_name} does not match VERSION={file_version}"
        )
    if not _CORE_RE.fullmatch(main_version):
        raise ReleaseValidationError(
            f"origin/main VERSION is invalid: {main_version!r}"
        )
    if base_version != main_version:
        raise ReleaseValidationError(
            "historical release replay blocked: "
            f"tag base={base_version}, current origin/main VERSION={main_version}"
        )
    return ReleaseMetadata(
        tag_version=tag_version,
        base_version=base_version,
        prerelease=prerelease is not None,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag-name", required=True)
    parser.add_argument("--file-version", required=True)
    parser.add_argument("--main-version", required=True)
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        metadata = validate_release(
            tag_name=args.tag_name,
            file_version=args.file_version,
            main_version=args.main_version,
        )
    except ReleaseValidationError as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1

    lines = (
        f"version={metadata.tag_version}\n"
        f"base-version={metadata.base_version}\n"
        f"prerelease={'true' if metadata.prerelease else 'false'}\n"
    )
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(lines)
    else:
        print(lines, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
