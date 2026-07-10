# Codex Linux Baseline Handoff

Last updated: 2026-07-10

## Objective and gate

Establish a reproducible, tested Delft3D FM Linux baseline on the Pop!_OS desktop before making any macOS port changes. Follow the completion gate and privacy rules in the repository-root `AGENTS.md`.

## Git topology

Mac Studio checkout:

```text
/Users/thijs/projects/Delft3D
```

Mac remotes:

```text
origin    git@github.com:tdamsma/Delft3D.git
popos     popos:/home/thijs/git/Delft3D.git
upstream  https://github.com/Deltares/Delft3D.git
```

`origin` is the user's private fork. Never push to `upstream` or publish work without explicit approval.

Pop!_OS repositories:

```text
bare remote:      /home/thijs/git/Delft3D.git
working checkout: /home/thijs/projects/Delft3D
```

Use the configured SSH alias:

```text
ssh popos
```

The intended synchronization flow is: commit on the Mac, push to remote `popos`, then run `git pull --ff-only` in the Pop!_OS working checkout. The Pop!_OS machine does not need GitHub credentials for this workflow.

## Pop!_OS baseline facts

- Pop!_OS 22.04 LTS, x86_64, kernel `7.0.11-76070011-generic`.
- 16 logical CPUs, 31 GiB RAM, approximately 940 GiB free at discovery time.
- Docker client/server 29.1.3 is installed and usable without sudo.
- The checkout was clean and on `main` before this handoff update.
- The initial source commit was `7ad48fa442d5d59e71cfa739ab4c0d194db95986`.
- `AGENTS.md` was added in commit `1107ad4b2eea0856e1accc0eabff0f4a7dc4b2a2`.

## Container status and blocker

The repository-recommended image is:

```text
containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:oneapi-2024-ifx-release
```

Docker is working, but the first pull failed with:

```text
pull access denied, repository does not exist or may require authorization:
authorization failed: no basic auth credentials
```

The Deltares registry requires an interactive credential setup. Per `.devcontainer/delft3d/README.md`, obtain the Harbor CLI secret and authenticate on Pop!_OS without putting the secret in shell history:

```bash
docker login --username '<DELFTARES_EMAIL>' containers.deltares.nl
```

Enter the CLI secret at Docker's password prompt. Do not record the secret in this repository or agent output.

If registry access is unavailable, the documented fallback is to build the images locally. `ci/dockerfiles/linux/README.md` describes this. The local build must override the private base with `almalinux:8`; the Dockerfile's private `# syntax=` frontend may also need a narrowly scoped portability adjustment. Prefer registry login first because it produces the supported baseline with fewer variables.

## Next actions

1. Verify registry authentication by pulling the pinned image:

   ```bash
   ssh popos 'docker pull containers.deltares.nl/delft3d-dev/delft3d-third-party-libs:oneapi-2024-ifx-release'
   ```

2. Inspect the image environment and `build.py --help` before choosing mount/user/cache arguments.
3. Create a persistent Conan Docker volume.
4. Run `python run_conan.py initialize deltares` if Nexus credentials are available; otherwise use `external` and build missing Conan dependencies locally.
5. Build `fm-suite` in Release mode with the repository wrapper.
6. Save full build logs outside Git under a clearly named build/log directory.
7. Run CTest, investigate failures, and produce the Linux completion-gate report described in `AGENTS.md`.
8. Inventory portability constraints encountered, but do not begin macOS source changes until the Linux gate is satisfied.

## Codex project permissions

Recommended Codex policy for this trusted checkout is `workspace-write`, `approval_policy = "on-request"`, and outbound network enabled. This permits normal repository work while retaining approval boundaries for protected paths and broader machine changes. Remote sudo and registry passwords still require the user to enter credentials interactively.
