# Task 18 Report: Podman Quadlet unit and deployment README

## Files created

1. `/run/media/vyshak/ssd/docviewer/.env.example`
2. `/run/media/vyshak/ssd/docviewer/docviewer.container`
3. `/run/media/vyshak/ssd/docviewer/README.md`

No code changes; no git operations were performed (per instructions).

## `.env.example`

Contains the brief's `SESSION_SECRET=changeme-generate-with-openssl-rand-hex-32`
line, plus a commented block explaining that `FILES_ROOT`, `DB_PATH`, and
`CACHE_DIR` are baked into the container image via `ENV` in the Containerfile
(confirmed by reading `Containerfile`: `ENV FILES_ROOT=/data/files
DB_PATH=/data/db/docviewer.sqlite3 CACHE_DIR=/data/cache`) and are therefore
**not** needed in the deployed `docviewer.env`, but are needed (uncommented,
edited to local paths) for local development, since `app/config.py`'s
`Settings` class declares `files_root`, `db_path`, `cache_dir`,
`session_secret` all as required fields with no defaults. This is a small,
low-risk addition beyond the brief's literal one-line content, added because
the brief's own README text ("edit FILES_ROOT/DB_PATH/CACHE_DIR/SESSION_SECRET
for local paths") implies the reader needs to know what those keys are
called, which a bare `SESSION_SECRET`-only file doesn't tell them.

## `docviewer.container`

Same structure as the brief's sample, with `Volume=` lines updated to add
`:U,Z` (see decision below). Deployment paths (`%h/docviewer-data/...`),
`Image=localhost/docviewer:local`, `PublishPort=127.0.0.1:8000:8000`,
`EnvironmentFile=%h/docviewer-data/docviewer.env`, `Restart=always`, and
`WantedBy=default.target` are unchanged from the brief.

## `README.md`

Same structure/content as the brief's sample (deploy steps, local dev
section), with one added subsection, "A note on the `:U,Z` volume flags",
explaining the SELinux/UID-mapping rationale so a future reader (or the
person running the real deploy) understands why the unit differs from a
naive `Volume=host:container` mount. No `podman run -v` examples exist
elsewhere in the README that needed updating — the only volume-related
commands in the README are `mkdir`/`ln -s` (no flags needed) and the Quadlet
unit reference.

## SELinux volume-flag decision: `:U,Z` (not `:U,z`)

Per `man 1 podman-run` (confirmed on this host, `/usr/share/man/man5/podman-systemd.unit.5.gz`
and `podman-run(1)` are present) and `man 5 podman-systemd.unit`'s `Volume=`
entry ("equivalent to the Podman `--volume` option"):

- `:U` — tells Podman to recursively chown the host-side mount source to the
  host UID/GID that corresponds to the UID/GID *inside* the container,
  accounting for rootless Podman's user-namespace remapping. Without it, the
  container's `appuser` (uid 1000 inside the container) cannot write to a
  directory owned by the host user, because rootless Podman maps container
  uid 1000 to a *different*, subuid-range-derived UID on the host (confirmed
  below: 525287, from this host's `/etc/subuid: vyshak:524288:65536`).
- `:Z` (uppercase) vs `:z` (lowercase) — both relabel for SELinux, but `Z`
  applies a **private/unshared** label (only the mounting container may use
  it) while `z` applies a **shared** label (any container may use it). I
  used `Z` because each of `~/docviewer-data/{files,state,state-cache}` is a
  dedicated directory for the one docviewer container, never shared with
  another container — matching your instruction to prefer `Z` for this case.
  Task 17's report used `:U,z` in its ad hoc verification run; I intentionally
  used `:U,Z` here since these are private, single-container mounts, not
  shared ones — `z` would still work but grants broader (shared-label)
  access than the deployment actually needs.

Both flags are combinable and comma-separated in the same `OPTIONS` field,
per `podman-run(1)`'s documented `[[SOURCE-VOLUME|HOST-DIR:]CONTAINER-DIR[:OPTIONS]]`
syntax — `:U,Z` is valid syntax, not something invented for this task.

## Verification performed

Environment: `getenforce` → `Enforcing`; `id` → `uid=1000(vyshak)
gid=1000(vyshak)`; `/etc/subuid` → `vyshak:524288:65536`; Podman 5.8.4,
rootless (`podman info --format '{{.Host.Security.Rootless}}'` → `true`).

### 1. `Image=` cross-check

`podman images | grep docviewer` → `localhost/docviewer  local  ...` — matches
`Image=localhost/docviewer:local` in `docviewer.container` exactly (this is
the tag Task 17 actually built and live-verified).

### 2. Quadlet syntax validation via the real generator

The Quadlet generator binary exists on this machine at
`/usr/lib/systemd/user-generators/podman-user-generator`. I copied the actual
`docviewer.container` file into a scratch source dir and ran the generator
against it directly (`QUADLET_UNIT_DIRS=<scratch-src>
podman-user-generator -v <scratch-out> <scratch-out> <scratch-out>`). It
parsed cleanly (no warnings/errors) and produced a `docviewer.service` unit,
including this `ExecStart` line, which is the ground-truth translation of the
Quadlet unit's directives:

```
ExecStart=/usr/bin/podman run --name systemd-%N --replace --rm --cgroups=split --sdnotify=conmon -d \
  -v %h/docviewer-data/files:/data/files:U,Z \
  -v %h/docviewer-data/state:/data/db:U,Z \
  -v %h/docviewer-data/state-cache:/data/cache:U,Z \
  --publish 127.0.0.1:8000:8000 \
  --env-file %h/docviewer-data/docviewer.env \
  localhost/docviewer:local
```

This also confirms the container's runtime name is `systemd-docviewer`
(`systemd-%N` with unit name `docviewer`), matching the brief's `podman exec
-it systemd-docviewer python -m scripts.create_user` instruction in the
README verbatim.

### 3. Manual `podman run` against a scratch directory (proves the `:U,Z` flags actually work here)

Created scratch dirs (`.../scratchpad/qtest-data/{files,state,state-cache}`,
owned by `vyshak:vyshak`, default/unlabeled) and a scratch env file with a
real `SESSION_SECRET`, then ran the manual equivalent of the generated
`ExecStart` (different container name/port to avoid clashing with anything
real):

```
podman run -d --name qtest-docviewer \
  -p 127.0.0.1:18000:8000 \
  -v <scratch>/qtest-data/files:/data/files:U,Z \
  -v <scratch>/qtest-data/state:/data/db:U,Z \
  -v <scratch>/qtest-data/state-cache:/data/cache:U,Z \
  --env-file <scratch>/qtest.env \
  localhost/docviewer:local
```

Result: container started and stayed up (`podman ps` → `Up ... 127.0.0.1:18000->8000/tcp`).
Logs showed clean startup (`Uvicorn running on http://0.0.0.0:8000`), no
SELinux AVC-denial-style errors.

`curl http://127.0.0.1:18000/healthz` → `HTTP 200`, body `{"status":"ok"}`.

Write test from inside the container, as the actual `appuser`:

```
podman exec qtest-docviewer sh -c 'id; touch /data/files/hello_from_container.txt && ls -la /data/files && touch /data/db/test.sqlite3 && touch /data/cache/test.cache'
```
→ `uid=1000(appuser) gid=1000(appuser)`, all three touches succeeded (no
permission errors) — proving all three mounts (`/data/files`, `/data/db`,
`/data/cache`) are genuinely writable by `appuser`, not just readable.

Host-side ownership check (`ls -laZ` on the scratch `files` dir) after the
container write:

```
drwxr-xr-x. 2 525287 525287 system_u:object_r:container_file_t:s0:c815,c958  ... files/
-rw-r--r--. 1 525287 525287 system_u:object_r:container_file_t:s0:c815,c958  ... hello_from_container.txt
```

This is exactly the expected result under enforcing SELinux + rootless
user-namespace remapping:
- UID/GID `525287` = `524288` (this host's subuid/subgid start) + `1000` −
  `1` (the container-side uid) → confirms `:U` correctly remapped ownership
  to the host UID that rootless Podman's user namespace actually maps
  container uid 1000 to, not to the host's own uid 1000 (`vyshak`).
- SELinux type `container_file_t` with a per-mount category pair
  (`c815,c958`) is the private/unshared MCS label `Z` is documented to apply
  (as opposed to `z`'s shared category set) — confirms `Z` (not `z`) is what
  actually got applied, and that it's sufficient for the container to
  read/write under `Enforcing` mode (no AVC denials observed).

### 4. Cleanup

`podman stop qtest-docviewer && podman rm qtest-docviewer` — removed.
Scratch directories were owned by the subuid-mapped uid `525287`, so a plain
host-side `rm -rf` failed with `Permission denied` on the container-written
files (further incidental confirmation of the UID remapping); cleaned up
correctly with `podman unshare rm -rf <scratch>/qtest-data`, which entered
the same user namespace Podman uses and could therefore remove them. Scratch
env file and Quadlet-generator scratch dirs were also removed. No test
containers or scratch data remain; `podman ps -a --filter name=qtest-docviewer`
returns empty.

## Deviations from the brief

1. **`Volume=` flags**: `:Z` → `:U,Z` on all three `Volume=` lines in
   `docviewer.container` (brief had plain `:Z`), and the README's local dev
   section is unchanged (no `podman run -v` examples existed elsewhere in the
   README that needed flags — the brief's README sample only used `Volume=`
   inside the Quadlet unit, plus plain `mkdir`/`ln -s` for directory setup,
   neither of which are volume-mount syntax). This was mandated by the task
   instructions, not a judgment call on my part beyond choosing `Z` over `z`
   (see decision section above).
2. **`.env.example` expanded** beyond the brief's single `SESSION_SECRET`
   line with a commented explanation of `FILES_ROOT`/`DB_PATH`/`CACHE_DIR`,
   to make the README's local-dev instruction ("edit
   FILES_ROOT/DB_PATH/CACHE_DIR/SESSION_SECRET for local paths") actually
   actionable from the file alone. Content and behavior for the *deployed*
   container are unaffected (those three vars are still supplied via the
   Containerfile's `ENV`, not `docviewer.env`).
3. **Step 4 ("manual verification") not performed as written** — the brief's
   version requires the actual target Fedora server with its real
   systemd/cloudflared setup, which this environment doesn't have access to.
   Per the task instructions, I substituted the four checks described above
   (image tag cross-check, Quadlet generator syntax validation, a real
   `podman run` exercising the exact `:U,Z` flags end-to-end with a
   healthz check and an ownership-verified write test, and cleanup) as the
   feasible subset of verification on this machine.

## Notes for whoever deploys this on the real server

- The Quadlet unit as written assumes a rootless *user* systemd service
  (`~/.config/containers/systemd/docviewer.container`, `systemctl --user`),
  matching the brief and the README. If deployed system-wide instead
  (`/etc/containers/systemd/`), `%h` won't resolve the same way and the
  paths would need to be absolute instead of home-relative — not something
  this task's brief called for, so left as-is.
- The `:U` chown walk is recursive and, per `podman-run(1)`, can be slow on
  large directories on first start. For a small test dir this was
  instantaneous; the real document collection may take noticeably longer
  the first time the service starts after `FILES_ROOT` is pointed at it.
