# Image publication gate

`docker.yml` checks all branches and PRs. Only dev, v-prefixed tags and the weekly
schedule publish. The schedule checks out dev and keeps `pull: true` and
`no-cache: true`. The version arguments BUILD_COMMIT, BUILD_TIME and BUILD_BRANCH
are captured once from the actual checkout and passed to the single build.

## Data flow

```text
checkout -> metadata -> ONE amd64+arm64 build -> runner-local OCI archive
  -> skopeo copy --all --preserve-digests -> runner-local registry:ci
  -> verify raw index digest equals build output; require both platform manifests
  -> pull index@sha256 for amd64 -> existing required smoke + informational YouTube
  -> pull SAME index@sha256 for arm64 -> existing offline smoke under QEMU
  -> TESTED_DIGEST -> login (publication refs only)
  -> skopeo copy --all --preserve-digests from local index@sha256 to official tags
  -> read back EVERY official tag -> require published digest == tested digest
```

The local registry is needed because Docker cannot directly run an OCI archive.
It listens on runner loopback only. A bind directory supplies registry storage;
no named volume or temporary ghcr tag is created. The archive, registry container
and directory are removed by an `always()` step; runner disposal also removes
them on cancellation. There are no remote staging versions to accumulate and
no package deletion permission is needed. Feature branches do not log in or
write any external image tags. OCI labels are attached before the one build.

The copied source is the immutable index reference used by both smoke commands.
`--all` preserves both platform manifests (and BuildKit attestations in the
index); `--preserve-digests` rejects conversions that would alter any digest.
`tools/ci_image_digest.py` additionally hashes `skopeo inspect --raw` bytes, rather
than an architecture-specific image ID or JSON re-serialization. The staged
index must match the build output, contain exactly one linux/amd64 and one
linux/arm64 manifest, and resolve through its digest reference before testing.
A source mismatch fails before any official tag writes; copy/read-back failures
fail the job and never emit a successful publication digest.

The existing smoke helper is unchanged: startup/demo healthz, imports, executable
and package versions, offline audio tools, and public SoundCloud with Bandcamp
fallback are required on amd64. YouTube with bgutil only warns. Arm64 uses the
existing basic-only gate. A required failure skips login and publication.

## Credentials and limits

Publication uses the existing workflow `GITHUB_TOKEN` through docker/login-action
and skopeo's explicit Docker auth file. `contents: read` and `packages: write`
remain sufficient; the repository must have package write access. No additional
PAT, delete scope or API call is used. No credentials are needed for local staging.

Official tag updates are individual registry operations, not a transaction. A
network error can leave some tags updated even though the job fails; every image
successfully copied still came from the tested index. A concurrent independent
writer can move tags after verification. The workflow's existing concurrency
policy only serializes runs for the same Git ref. Builds on an ephemeral runner
need extra disk for the archive and registry and need skopeo/registry downloads.
The first run uses a new multiarch GHA cache scope; schedule still builds fresh.

## First GitHub run checklist

Check these log lines in order (all index digests must be identical):

- Build action digest and `DIGEST_CHECK OCI archive -> local registry`.
- `TEST_PLATFORM linux/amd64` and `TEST_PLATFORM linux/arm64` (child digests differ).
- Both `docker pull` commands use the same `localhost:5000/musicbot@sha256:...`.
- Existing smoke PASS lines and the `Record the digest that passed BOTH gates`
  step's `TESTED_DIGEST=sha256:...`; a YouTube warning is informational.
- `DIGEST_CHECK tested source before publication`.
- `PUBLISHED_TAG=... PUBLISHED_DIGEST=... TESTED_DIGEST=...` for every official tag.
- `DIGEST_MATCH=PASS TESTED_DIGEST=... PUBLISHED_DIGEST=...` and matching digest
  fields in the job summary. A feature/PR run has no published digest by design.
- Cleanup removed the runner-local storage. No second build or ghcr ci tag exists.

Local checks: `actionlint` and `python3 -m unittest tools.test_ci_image_digest`.
A registry simulation may pass `--dest-insecure` to the helper only for a
`localhost:<port>/...` destination. Never use that option for ghcr.
