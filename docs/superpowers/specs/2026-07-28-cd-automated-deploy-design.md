# CD Automated Deploy — Design Spec

- **Date:** 2026-07-28
- **Status:** Approved design, pending implementation plan
- **Scope:** Extend the existing CI workflow with an automated deploy step and a code-style gate (`ruff`); no changes to the manual-deploy runbook in `DEPLOY.md` (it stays as the documented fallback / rollback procedure)

## Goal

Deployment today is fully manual: SSH into the EC2 instance, `git pull`, `docker build` (on the production box itself), stop/remove the old container, run a new one. This works but means every change requires a human to remote in and repeat the same steps, and building on the production server means the image running in prod was never independently verified — it's whatever `docker build` produced on that specific machine at that moment.

This spec adds a CD step that, on every push to `master` that passes the existing test suite, builds the Docker image once in GitHub Actions, pushes it to GitHub Container Registry (GHCR), and has the EC2 instance pull and run that exact same image. What ran in CI is what runs in production — no rebuild-on-prod drift.

## Non-goals

- No zero-downtime deployment (blue-green, rolling, load balancer). Single EC2 instance; a few seconds of downtime during container swap is accepted.
- No change to how `.env` is managed — it stays on the server, untouched by the deploy pipeline. The pipeline only ever swaps the image, never touches secrets.
- No deploy on pull requests — only on push to `master`, after tests pass.
- Does not replace the manual deploy steps documented in `DEPLOY.md` §4 — those remain the documented procedure for first-time setup and manual rollback.

## Code style gate (added scope)

The existing `test` job runs `pytest` only — no linting or formatting is enforced anywhere in the project today. Two additions:

1. **CI gate**: `test` job gets two new steps, before `pytest`: `ruff check .` (lint) and `ruff format --check .` (formatting, fails if any file isn't already formatted — doesn't auto-fix in CI). Chose `ruff` over the older flake8+black+isort combo — one fast tool, one config block, does both jobs.
2. **One-time repo formatting pass**: since no code has ever been run through `ruff`, turning on `ruff format --check` cold would fail on the first run. As part of implementing this, run `ruff format .` and `ruff check --fix .` once across the existing codebase and commit the result *before* the CI gate is turned on, so the gate starts green.

Because this lives inside the existing `test` job (not a new parallel job), the dependency graph doesn't change: `build-and-deploy` still just does `needs: test`, and a lint/format failure blocks deploy exactly the same way a test failure already does — no separate wiring needed.

## Architecture

```
push to master
      │
      ▼
GitHub Actions: test job (existing job, gains ruff check + ruff format --check
                 as new steps before pytest)
      │ needs: passes
      ▼
GitHub Actions: build-and-deploy job (new)
      │
      ├─ docker build -t ghcr.io/jasonpaul0727/po-agents:<commit-sha> .
      ├─ docker push ghcr.io/jasonpaul0727/po-agents:<commit-sha>
      ├─ docker tag/push ghcr.io/jasonpaul0727/po-agents:latest
      │
      ▼
SSH to EC2 (dedicated CI deploy key, not the operator's personal key)
      │
      ├─ docker pull ghcr.io/jasonpaul0727/po-agents:<commit-sha>
      ├─ docker stop po-intake && docker rm po-intake
      ├─ docker run -d --name po-intake \
      │     --env-file .env \
      │     -v po_data:/app/data \
      │     -p 127.0.0.1:8000:8000 \
      │     --restart unless-stopped \
      │     ghcr.io/jasonpaul0727/po-agents:<commit-sha>
      └─ container running the exact image that passed CI
```

## Components

**GHCR image, public visibility.** The source repo is already public and the image contains no secrets (`.env` is git/docker-ignored, never baked into a layer), so there's no reason to gate pulls behind authentication — the server does a plain `docker pull`, no `docker login` step or token to manage on the EC2 box.

**Dual image tags**: every build pushes both `<commit-sha>` (permanent, enables rollback to any prior version) and `latest` (convenience pointer to the most recent build). Rollback is `docker pull ghcr.io/.../po-agents:<old-sha>` followed by the same stop/rm/run sequence, substituting the old tag — no rebuild needed since the old image is already in the registry.

**Dedicated CI deploy SSH key.** A new keypair generated specifically for this workflow (`ssh-keygen`, no passphrase since it must run unattended). Public key appended to the EC2 instance's `~/.ssh/authorized_keys`; private key stored as a GitHub Actions repository secret (`DEPLOY_SSH_KEY`) and never written to disk outside the Actions runner's ephemeral environment. This is separate from the operator's personal `po-agents-key.pem` — a leak of the CI key only grants deploy-level SSH access, not the operator's own credential.

**New GitHub Actions secrets required**:
- `DEPLOY_SSH_KEY` — the CI deploy private key
- `DEPLOY_HOST` — `3.17.209.141` (or the domain, `yanxiabu001.com`)
- `DEPLOY_USER` — `ubuntu`

GHCR push auth uses the built-in `GITHUB_TOKEN` (no new secret needed), with `packages: write` permission granted to the job.

## Data flow

No application data flows through the pipeline. The only thing that moves is the image (registry) and the SSH commands (control plane). `po.db` (via the `po_data` volume) and `.env` are never touched by CD — they persist on the server across every deploy, exactly as they do with manual deploys today.

## Error handling

- **Test job fails** → `build-and-deploy` never starts (`needs: test` in the workflow). No image is built or pushed.
- **Build or push to GHCR fails** → workflow fails before ever touching the server. The running container is untouched.
- **SSH connection fails** → workflow fails; running container untouched (the pull step, which happens before stop/rm, never ran).
- **`docker pull` on the server fails** (bad tag, network issue) → the deploy script stops here, before `docker stop`/`docker rm`. The old container is still running the previous version — no window where nothing is running.
- **New container fails to start** (bad image, crash on boot) → this is the one real gap: the old container has already been removed by this point. Mitigation for this spec: the deploy script checks `docker ps` for the new container's `Up` status a few seconds after `docker run`; if it isn't up, the workflow fails loudly (so the operator knows to manually roll back via the documented rollback command) rather than silently leaving the site down. Automatic rollback-on-failure is out of scope here — YAGNI for a single-operator project; a failed deploy paging no one is an acceptable gap for now, given deploys are infrequent and manually triggered by a push.

## Testing

- The existing test suite (134 tests) is unchanged and remains the gate before any deploy happens — this spec doesn't add new test coverage, it adds an automated action that only runs after existing tests pass.
- Manual verification after implementation: push a trivial change to `master`, confirm the Actions run builds, pushes both tags to GHCR, SSHes in, and the new container comes up; verify via `curl https://yanxiabu001.com/` (401/200 pair) that the redeployed app is live and the auth guard still works.
- Rollback path gets exercised manually once during implementation (deploy two commits, roll back to the first by tag, confirm the app reflects the older version) to prove the documented procedure actually works before relying on it.
- After the one-time formatting pass, run the full test suite locally to confirm `ruff format`/`ruff check --fix` didn't change any runtime behavior (formatting-only tools shouldn't, but verify rather than assume) before turning the CI gate on.
