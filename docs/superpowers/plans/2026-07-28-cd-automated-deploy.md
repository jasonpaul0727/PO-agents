# CD Automated Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On every push to `master` that passes tests, automatically build the Docker image once in GitHub Actions, push it to GHCR, and have the EC2 instance pull and run that exact image — replacing the current fully-manual `git pull` + `docker build` (on the prod box) + restart routine. Also adds a `ruff` lint/format gate to the same CI run.

**Architecture:** Extend `.github/workflows/ci.yml`'s existing `test` job with `ruff check`/`ruff format --check` steps, then add a new `build-and-deploy` job (`needs: test`, only on push to `master`) that builds+pushes a dual-tagged (`<sha>` + `latest`) image to GHCR and SSHes into the EC2 instance with a dedicated deploy key to pull and restart the container. `.env` and the `po_data` volume are never touched by the pipeline.

**Tech Stack:** GitHub Actions, Docker, GitHub Container Registry (GHCR), `ruff`, OpenSSH.

## Global Constraints

- GHCR image path: `ghcr.io/jasonpaul0727/po-agents` (lowercase — GHCR/Docker require it; the repo itself is `jasonpaul0727/PO-agents`, case doesn't need to match).
- Image is **public** — no `docker login` needed on the server to pull.
- Every build pushes **two tags**: the full commit SHA (`${{ github.sha }}`) and `latest`.
- Deploy uses a **dedicated SSH keypair**, never the operator's personal `po-agents-key.pem`.
- Server details: host `3.17.209.141` (or `yanxiabu001.com`), user `ubuntu`, container name `po-intake`, volume `po_data:/app/data`, port binding `127.0.0.1:8000:8000`, restart policy `unless-stopped` — these must match the existing manual `docker run` invocation exactly (see `DEPLOY.md` §4/§7).
- `ruff` is a CI-only tool — do **not** add it to `requirements.lock.txt` (that file is also used to build the production Docker image; ruff has no business in the runtime image).
- Deploy only triggers on `push` to `master`, never on `pull_request`.
- Python target version: 3.12 (matches `Dockerfile`'s `python:3.12-slim`).

---

### Task 1: Add ruff config and run a one-time formatting pass

**Files:**
- Create: `pyproject.toml`
- Modify: any `.py` file under `backend/`, `tests/` that `ruff format`/`ruff check --fix` changes

**Interfaces:**
- Produces: a `pyproject.toml` with a `[tool.ruff]` block that Task 2's CI step reads implicitly (ruff auto-discovers config from the repo root).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
```

- [ ] **Step 2: Install ruff locally**

Run: `pip install ruff`
Expected: installs without error (this is a local/dev install, not added to any requirements file).

- [ ] **Step 3: Run the formatter and auto-fixable lint rules across the repo**

Run:
```bash
ruff format .
ruff check --fix .
```
Expected: prints a list of reformatted/fixed files. This will likely touch a large fraction of the 55 `.py` files in the repo — that's expected for a first run.

- [ ] **Step 4: Check for any lint errors ruff couldn't auto-fix**

Run: `ruff check .`
Expected: either `All checks passed!`, or a list of remaining issues. If there are remaining issues, fix each by hand (read the specific rule violation ruff reports — don't guess) until `ruff check .` is clean.

- [ ] **Step 5: Run the full test suite to confirm formatting didn't change behavior**

Run: `pytest tests backend/sample_request/tests -q`
Expected: same pass count as before this task (134 passed) — `ruff format`/`--fix` should only touch style, never behavior, but this step verifies that assumption rather than trusting it.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "style: add ruff config, run one-time format + lint-fix pass"
```

---

### Task 2: Add the ruff gate to the CI `test` job

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `pyproject.toml` from Task 1 (ruff reads it automatically, no explicit path needed in the workflow).

- [ ] **Step 1: Add ruff install + check steps to the `test` job, before the existing `pytest` step**

Modify `.github/workflows/ci.yml` — insert two new steps between "Install dependencies" and "Run tests":

```yaml
      - name: Install dependencies
        run: pip install -r requirements.lock.txt

      - name: Install ruff
        run: pip install ruff

      - name: Lint (ruff check)
        run: ruff check .

      - name: Format check (ruff format)
        run: ruff format --check .

      - name: Run tests
        run: pytest tests backend/sample_request/tests -q
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add ruff lint + format-check gate before tests"
```

- [ ] **Step 3: Push and verify the workflow run is green**

Run: `git push origin master`, then `gh run watch $(gh run list --branch master --limit 1 --json databaseId -q '.[0].databaseId')`
Expected: the `test` job completes successfully, including the two new ruff steps (they should pass because Task 1 already made the repo clean). If either ruff step fails here, it means Task 1's Step 4 missed something — go back and fix it, don't weaken the CI check.

---

### Task 3: Generate the CI deploy key and configure server + GitHub secrets

**Files:**
- None in the repo — this task only touches `~/.ssh/` (local) and the EC2 server's `~/.ssh/authorized_keys`, plus GitHub repository secrets.

**Interfaces:**
- Produces: GitHub secrets `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER` that Task 4's workflow job consumes by name.

- [ ] **Step 1: Generate a dedicated ed25519 keypair for CI deploys (no passphrase — must run unattended)**

Run:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/po-agents-ci-deploy -N "" -C "github-actions-deploy"
```
Expected: creates `~/.ssh/po-agents-ci-deploy` (private) and `~/.ssh/po-agents-ci-deploy.pub` (public).

- [ ] **Step 2: Install the public key on the EC2 server, using the existing personal key**

Run:
```bash
cat ~/.ssh/po-agents-ci-deploy.pub | ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141 "cat >> ~/.ssh/authorized_keys"
```
Expected: no output, exits cleanly.

- [ ] **Step 3: Verify the new key actually works before relying on it in CI**

Run: `ssh -i ~/.ssh/po-agents-ci-deploy -o StrictHostKeyChecking=no ubuntu@3.17.209.141 "whoami && docker --version"`
Expected: prints `ubuntu` and the Docker version — proves the new key can log in and the deploy user can run `docker` (already in the `docker` group from earlier setup).

- [ ] **Step 4: Add the three GitHub Actions secrets**

Run:
```bash
gh secret set DEPLOY_SSH_KEY < ~/.ssh/po-agents-ci-deploy
gh secret set DEPLOY_HOST --body "3.17.209.141"
gh secret set DEPLOY_USER --body "ubuntu"
```
Expected: each command prints a confirmation (e.g. `✓ Set Actions secret DEPLOY_SSH_KEY for jasonpaul0727/PO-agents`).

- [ ] **Step 5: Confirm the secrets are listed**

Run: `gh secret list`
Expected: shows `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER` in the list (values are never shown, only names + update timestamps — this is expected, GitHub never displays secret values back).

No commit for this task — nothing in the repo changed.

---

### Task 4: Add the `build-and-deploy` job

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: secrets `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER` from Task 3; the built-in `GITHUB_TOKEN` for GHCR auth; `${{ github.sha }}` for the image tag.

- [ ] **Step 1: Append the `build-and-deploy` job to `.github/workflows/ci.yml`**

Add at the end of the file (same indentation level as the existing `test` job, under `jobs:`):

```yaml
  build-and-deploy:
    needs: test
    if: github.ref == 'refs/heads/master' && github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/jasonpaul0727/po-agents:${{ github.sha }}
            ghcr.io/jasonpaul0727/po-agents:latest

      - name: Deploy to EC2
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            docker pull ghcr.io/jasonpaul0727/po-agents:${{ github.sha }}
            cd ~/PO-agents
            docker stop po-intake || true
            docker rm po-intake || true
            docker run -d --name po-intake \
              --env-file .env \
              -v po_data:/app/data \
              -p 127.0.0.1:8000:8000 \
              --restart unless-stopped \
              ghcr.io/jasonpaul0727/po-agents:${{ github.sha }}
            sleep 5
            docker ps --filter "name=po-intake" --filter "status=running" --format "{{.Names}}" | grep -q po-intake
```

Notes on this step, so the implementer understands the choices (don't second-guess and "simplify" them away):
- `docker stop`/`docker rm` use `|| true` because on the very first automated deploy there is no existing `po-intake` container yet (it was created manually) — without `|| true` the job would fail on a clean slate.
- The final `sleep 5` + `docker ps ... | grep -q po-intake` is the "did the new container actually come up" check from the spec's error-handling section — `grep -q` exits non-zero (failing the step, and the job) if the container isn't running, so a crash-on-boot doesn't get silently reported as a successful deploy.
- `cd ~/PO-agents` before `docker run` because `--env-file .env` is a relative path — must match how the manual deploy already runs it (see `DEPLOY.md` §4).

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add build-and-deploy job — GHCR push + SSH deploy to EC2"
```

Do not push yet — Task 5 verifies end-to-end together with this.

---

### Task 5: Update `DEPLOY.md` with the automated deploy process

**Files:**
- Modify: `DEPLOY.md`

- [ ] **Step 1: Add a new section documenting the automated flow and rollback procedure**

Add a new numbered section (following the existing `### N. Title` pattern already in the file) after the HTTPS section, before the status table, covering:
- What triggers it (push to `master`, after `test` job passes)
- Where the image lives (`ghcr.io/jasonpaul0727/po-agents`, public, tags = commit SHA + `latest`)
- That the manual steps in §4 are now the **fallback/rollback** procedure, not the primary path
- The rollback command:
  ```bash
  ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141
  cd ~/PO-agents
  docker pull ghcr.io/jasonpaul0727/po-agents:<old-sha>
  docker stop po-intake && docker rm po-intake
  docker run -d --name po-intake \
    --env-file .env \
    -v po_data:/app/data \
    -p 127.0.0.1:8000:8000 \
    --restart unless-stopped \
    ghcr.io/jasonpaul0727/po-agents:<old-sha>
  ```
- Update the status table: move "CD 自动部署" from 待办 to 完成, update the percentage.

- [ ] **Step 2: Commit**

```bash
git add DEPLOY.md
git commit -m "docs: document automated CD flow and rollback procedure"
```

---

### Task 6: End-to-end verification (push, watch, verify, test rollback)

**Files:** None — this task only runs commands and observes results.

- [ ] **Step 1: Push everything and watch the workflow run**

Run:
```bash
git push origin master
gh run watch $(gh run list --branch master --limit 1 --json databaseId -q '.[0].databaseId')
```
Expected: both `test` and `build-and-deploy` jobs complete successfully.

- [ ] **Step 2: Confirm both image tags exist in GHCR**

Run (from your local machine, not the server — proves the tags are pullable from outside, same as the server just did):
```bash
docker manifest inspect ghcr.io/jasonpaul0727/po-agents:latest > /dev/null && echo "latest: OK"
docker manifest inspect ghcr.io/jasonpaul0727/po-agents:$(git rev-parse HEAD) > /dev/null && echo "sha tag: OK"
```
Expected: both print `OK` — `docker manifest inspect` succeeds only if the tag exists and is publicly pullable (no auth needed, confirming the "public visibility" requirement from the spec too).

- [ ] **Step 3: Confirm the server is running the new image**

Run: `ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141 "docker inspect po-intake --format '{{.Config.Image}}'"`
Expected: prints `ghcr.io/jasonpaul0727/po-agents:<the commit sha you just pushed>`.

- [ ] **Step 4: Confirm the live site still works**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://yanxiabu001.com/
curl -s -o /dev/null -w "%{http_code}\n" -u demo:<password> https://yanxiabu001.com/
```
Expected: `401` then `200` — same as every prior verification in this project, now proving the *automated* deploy produces a working, still-authenticated site.

- [ ] **Step 5: Exercise the rollback procedure once, to prove it actually works**

Note the current commit SHA (the one just deployed) and the previous one (`git log --oneline -2`). Run the rollback commands from Task 5's Step 1 using the **previous** SHA. Then:

Run: `ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141 "docker inspect po-intake --format '{{.Config.Image}}'"`
Expected: now shows the **previous** SHA tag — confirms rollback worked.

- [ ] **Step 6: Redeploy the latest version to leave the server in the correct end state**

Run the same rollback-style commands but with the **current** (latest) SHA, so the server ends this task running the newest code, not the rollback test target.

Run: `ssh -i ~/.ssh/po-agents-key.pem ubuntu@3.17.209.141 "docker inspect po-intake --format '{{.Config.Image}}'"`
Expected: back to the current/latest SHA.

- [ ] **Step 7: Final commit — none needed**

This task is verification-only; if all steps passed, the plan is complete. If any step failed, fix the root cause (don't paper over it) and re-run from Step 1.
