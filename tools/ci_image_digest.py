#!/usr/bin/env python3
"""Copy a multiarch OCI candidate without rebuilding or changing its digest.

The local registry is disposable and contains no credentials. Publication only
runs after both smoke gates; IMAGE_TAGS is the metadata action's newline list.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class DigestFailure(Exception):
    pass


def note(message):
    print(message, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"- {message}\n")


def output(key, value):
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"{key}={value}\n")


def validate_digest(digest):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise DigestFailure("Expected a nonempty sha256 manifest digest")


def local_repository(repository):
    if not re.fullmatch(r"localhost:[0-9]+/[a-z0-9/_-]+", repository):
        raise DigestFailure("Insecure transport is restricted to a localhost repository")


def inspect(reference, *, insecure=False, authfile=None):
    command = ["skopeo", "inspect", "--raw"]
    if insecure:
        command.append("--tls-verify=false")
    if authfile:
        command += ["--authfile", authfile]
    raw = subprocess.check_output([*command, "docker://" + reference])
    # Hash the original bytes, never a parsed/re-serialized manifest or image ID.
    return "sha256:" + hashlib.sha256(raw).hexdigest(), json.loads(raw)


def require_same(expected, actual, label):
    note(f"DIGEST_CHECK {label} expected={expected} actual={actual}")
    if expected != actual:
        raise DigestFailure(f"Digest mismatch at {label}; publication is not verified")


def require_platforms(index):
    for architecture in ("amd64", "arm64"):
        matches = [entry for entry in index.get("manifests", [])
                   if entry.get("platform", {}).get("os") == "linux"
                   and entry.get("platform", {}).get("architecture") == architecture]
        if len(matches) != 1:
            raise DigestFailure(f"Expected exactly one linux/{architecture} manifest")
        validate_digest(matches[0]["digest"])
        note(f"TEST_PLATFORM linux/{architecture} manifest={matches[0]['digest']}")


def stage(args):
    validate_digest(args.digest)
    local_repository(args.repository)
    destination = args.repository + ":ci"
    subprocess.run([
        "skopeo", "copy", "--all", "--preserve-digests", "--dest-tls-verify=false",
        "oci-archive:" + str(Path(args.archive).resolve()), "docker://" + destination,
    ], check=True)
    actual, index = inspect(destination, insecure=True)
    require_same(args.digest, actual, "OCI archive -> local registry")
    require_platforms(index)
    reference = args.repository + "@" + args.digest
    # Also prove the immutable reference itself resolves before any smoke tests.
    pinned, _ = inspect(reference, insecure=True)
    require_same(args.digest, pinned, "candidate digest reference")
    note(f"CANDIDATE_DIGEST={args.digest}")
    output("digest", args.digest)
    output("reference", reference)


def publish(args):
    validate_digest(args.digest)
    source_repository, separator, source_digest = args.source.partition("@")
    local_repository(source_repository)
    if not separator or source_digest != args.digest:
        raise DigestFailure("Publication source must be pinned to the tested digest")
    if args.dest_insecure:
        local_repository(args.repository)
    tags = list(dict.fromkeys(os.environ.get("IMAGE_TAGS", "").splitlines()))
    if not tags or any(not re.fullmatch(re.escape(args.repository) + r":[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag)
                       for tag in tags):
        raise DigestFailure("Official tags must be nonempty and belong to the expected repository")
    actual, index = inspect(args.source, insecure=True)
    require_same(args.digest, actual, "tested source before publication")
    require_platforms(index)
    for tag in tags:
        command = ["skopeo", "copy", "--all", "--preserve-digests", "--src-tls-verify=false"]
        if args.authfile:
            command += ["--dest-authfile", args.authfile]
        if args.dest_insecure:
            command.append("--dest-tls-verify=false")
        subprocess.run([*command, "docker://" + args.source, "docker://" + tag], check=True)
    # Read back ALL tags after all copies, including an accidentally moved tag.
    for tag in tags:
        actual, _ = inspect(tag, insecure=args.dest_insecure, authfile=args.authfile)
        note(f"PUBLISHED_TAG={tag} PUBLISHED_DIGEST={actual} TESTED_DIGEST={args.digest}")
        require_same(args.digest, actual, tag)
    note(f"DIGEST_MATCH=PASS TESTED_DIGEST={args.digest} PUBLISHED_DIGEST={args.digest}")
    output("digest", args.digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    staging = commands.add_parser("stage")
    staging.add_argument("archive")
    staging.add_argument("digest")
    staging.add_argument("repository")
    publishing = commands.add_parser("publish")
    publishing.add_argument("source")
    publishing.add_argument("digest")
    publishing.add_argument("repository")
    publishing.add_argument("--authfile")
    publishing.add_argument("--dest-insecure", action="store_true", help="Local registry simulation only")
    args = parser.parse_args()
    try:
        (stage if args.command == "stage" else publish)(args)
        return 0
    except (DigestFailure, OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        note(f"DIGEST_MATCH=FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
