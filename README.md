# docviewer

Lightweight, self-hosted PDF/docx/text viewer and file manager. See
`docs/superpowers/specs/2026-08-25-docviewer-design.md` for the full design.

## Deploy (Fedora Server, rootless Podman)

1. Build the image: `podman build -t docviewer:local -f Containerfile .`
2. Create data directories:
   ```bash
   mkdir -p ~/docviewer-data/state ~/docviewer-data/state-cache
   # point files at your existing document collection, e.g. a bind mount or symlink:
   ln -s /path/to/existing/documents ~/docviewer-data/files
   ```
3. Create `~/docviewer-data/docviewer.env` from `.env.example` (it has no
   required variables to fill in for the deployed container — see the file's
   comments — but `EnvironmentFile=` in `docviewer.container` expects it to
   exist).
4. Copy `docviewer.container` to `~/.config/containers/systemd/`.
5. Reload and start:
   ```bash
   systemctl --user daemon-reload
   systemctl --user start docviewer.service
   systemctl --user enable docviewer.service
   ```
6. Provision the one user account:
   ```bash
   podman exec -it systemd-docviewer python -m scripts.create_user
   ```
   Scan the printed QR/URI into an authenticator app (Aegis, Google
   Authenticator, etc).
7. Point your existing `cloudflared` tunnel at `127.0.0.1:8000` under a new
   hostname (e.g. `files.yourdomain.com`), in `~/.cloudflared/config.yml`:
   ```yaml
   ingress:
     - hostname: files.yourdomain.com
       service: http://127.0.0.1:8000
     # ...your other existing ingress rules...
   ```
   Then `systemctl restart cloudflared` (or however your existing tunnel
   service is managed).

### A note on the volume flags

This host runs **rootless Podman with SELinux in Enforcing mode**, under
which a plain `Volume=host:container` bind mount does not work correctly by
default:

- **UID mapping (`:U`)**: rootless Podman runs the container's processes
  inside a user namespace, so the `appuser` (uid 1000 *inside* the container)
  is not the same as uid 1000 on the host — it's remapped through your
  `/etc/subuid` range. Without `:U`, the bind-mounted host directory keeps
  its host ownership and `appuser` cannot write to it. `:U` tells Podman to
  chown the mount's contents (once, at container start) to the host
  UID/GID that actually corresponds to the container's uid/gid, so
  `appuser` ends up with real read/write access.
- **SELinux labeling (`:Z`/`:z`)**: SELinux blocks a confined container
  process from touching a bind-mounted host directory that doesn't carry a
  container-accessible label, independently of Unix permissions (this shows
  up as `Permission denied` even when the UID/GID line up). Capital `Z`
  relabels the directory with a **private**, unshared SELinux label;
  lowercase `z` uses a **shared** label instead.

**The `state` and `state-cache` volumes use `:U,Z`.** Both are dedicated
directories that exist solely for this app (nothing else reads or writes
them), so it's safe to let Podman chown and privately relabel them on first
start.

**The `files` volume deliberately does *not* use `:U`, and uses lowercase
`:z` instead of `:Z`.** This volume typically points at (or symlinks to) the
user's *existing* document collection — a directory that predates docviewer,
is owned by the user's own account, and may be read or written by other
things (Samba, backup jobs, a desktop file manager, etc). `:U` recursively
`chown`s the entire mount to the container's mapped UID/GID on every first
start; on a real, possibly large document tree this would silently reassign
ownership away from the user's own account, breaking their own shell access
to those files and potentially breaking whatever else touches that directory.
`:Z` (capital) would similarly relabel the whole tree with a private
SELinux label, which could break other confined processes that also need to
read it. Instead, the container's UID mapping is handled once, container-wide,
via `UserNS=keep-id:uid=1000,gid=1000` in the `[Container]` section — this
maps the container's uid 1000 directly to the *invoking host user's* uid, so
`appuser` can read/write files the host user already owns without any
recursive chown of the source tree. The lowercase `:z` SELinux flag applies a
shared label, appropriate since this directory isn't exclusively docviewer's.
If your document collection needs a one-time ownership or label fix before
first start, do that manually and deliberately (e.g. `chown -R` / `chcon -R`
yourself) rather than delegating it to Podman on every container start.

This was verified on this machine (rootless Podman, `getenforce` =
`Enforcing`): the Quadlet unit was run through the actual
`podman-user-generator` and parsed cleanly, producing an `ExecStart` with
`--userns keep-id:uid=1000,gid=1000` and `-v host:/data/files:z` (no `U`) for
the files mount, alongside `-v host:/data/db:U,Z` and
`-v host:/data/cache:U,Z` for the state volumes — confirming the unit's
syntax and flag placement are correct. A full live re-verification against a
real pre-existing document tree (owned by another account, to confirm
`keep-id` avoids the chown/relabel and still grants access) was not
performed in this environment and should be done once on the real deployment
target before relying on it with irreplaceable data.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # edit FILES_ROOT/DB_PATH/CACHE_DIR for local paths
pytest
uvicorn app.main:app --reload
```

Note: local dev without the container won't have `app/static/vendor/`
populated (that's assembled by the Containerfile build) — the login page
and file browser work, but PDF/docx/markdown preview will 404 on vendored
assets until you either build the container or manually populate
`app/static/vendor/` yourself.
