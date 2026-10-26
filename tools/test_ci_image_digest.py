#!/usr/bin/env python3
"""Regression checks for the OCI publication gate; no registry or credentials."""
import argparse
import hashlib
import os
import unittest
from unittest.mock import patch

from tools import ci_image_digest as gate

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
INDEX = {"manifests": [
    {"platform": {"os": "linux", "architecture": arch}, "digest": DIGEST}
    for arch in ("amd64", "arm64")
]}


class DigestGateTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"IMAGE_TAGS": "localhost:5000/release:sha-test\nlocalhost:5000/release:latest"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.args = argparse.Namespace(source="localhost:5000/musicbot@" + DIGEST,
                                       digest=DIGEST, repository="localhost:5000/release",
                                       authfile=None, dest_insecure=True)

    def test_hashes_raw_manifest_bytes(self):
        raw = b'{ "schemaVersion": 2, "manifests": [] }'
        with patch.object(gate.subprocess, "check_output", return_value=raw):
            digest, _ = gate.inspect("localhost:5000/musicbot:ci", insecure=True)
        self.assertEqual(digest, "sha256:" + hashlib.sha256(raw).hexdigest())

    def test_missing_or_duplicate_architecture_rejected(self):
        for entries in (INDEX["manifests"][:1], INDEX["manifests"] * 2):
            with self.subTest(entries=entries), self.assertRaises(gate.DigestFailure):
                gate.require_platforms({"manifests": entries})

    def test_stage_digest_mismatch_emits_no_candidate_output(self):
        args = argparse.Namespace(archive="candidate.tar", digest=DIGEST, repository="localhost:5000/musicbot")
        with patch.object(gate.subprocess, "run"), patch.object(gate, "inspect", return_value=(OTHER, INDEX)), patch.object(gate, "output") as output:
            with self.assertRaises(gate.DigestFailure):
                gate.stage(args)
            output.assert_not_called()

    def test_source_mismatch_never_copies(self):
        with patch.object(gate, "inspect", return_value=(OTHER, INDEX)), patch.object(gate.subprocess, "run") as copy:
            with self.assertRaises(gate.DigestFailure):
                gate.publish(self.args)
            copy.assert_not_called()

    def test_unpinned_source_never_copies(self):
        self.args.source = "localhost:5000/musicbot:ci"
        with patch.object(gate.subprocess, "run") as copy:
            with self.assertRaises(gate.DigestFailure):
                gate.publish(self.args)
            copy.assert_not_called()

    def test_readback_mismatch_emits_no_success_output(self):
        with patch.object(gate, "inspect", side_effect=[(DIGEST, INDEX), (OTHER, INDEX)]), patch.object(gate.subprocess, "run"), patch.object(gate, "output") as output:
            with self.assertRaises(gate.DigestFailure):
                gate.publish(self.args)
            output.assert_not_called()

    def test_every_tag_copied_with_preserve_digests_and_all_then_read_back(self):
        events = []
        def inspect(reference, **kwargs):
            events.append(("inspect", reference))
            return DIGEST, INDEX
        def copy(command, **kwargs):
            events.append(("copy", command[-1]))
            self.assertIn("--all", command)
            self.assertIn("--preserve-digests", command)
            self.assertIn("docker://" + self.args.source, command)
        with patch.object(gate, "inspect", side_effect=inspect), patch.object(gate.subprocess, "run", side_effect=copy), patch.object(gate, "output") as output:
            gate.publish(self.args)
        self.assertEqual([event[0] for event in events], ["inspect", "copy", "copy", "inspect", "inspect"])
        output.assert_called_once_with("digest", DIGEST)

    def test_empty_or_foreign_tags_rejected_before_copy(self):
        for tags in ("", "elsewhere/image:latest"):
            with self.subTest(tags=tags), patch.dict(os.environ, {"IMAGE_TAGS": tags}), patch.object(gate.subprocess, "run") as copy:
                with self.assertRaises(gate.DigestFailure):
                    gate.publish(self.args)
                copy.assert_not_called()

    def test_insecure_destination_must_be_loopback(self):
        self.args.repository = "ghcr.io/example/musicbot"
        with self.assertRaises(gate.DigestFailure):
            gate.publish(self.args)


if __name__ == "__main__":
    unittest.main()
