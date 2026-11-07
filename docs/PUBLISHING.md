# Publishing checklist

Everything below the line "Done in the repository" is already prepared. The steps in "You do" cannot be done
from the development environment: they create public, hard-to-undo things (a name, a public repository,
a container image). Do them in this order.

## Done in the repository

- HACS layout: one integration in `custom_components/<domain>/`, `hacs.json`, README, license.
- `manifest.json` accepted by Home Assistant's `hassfest` and by HACS's own manifest schemas (both run locally
  against Home Assistant 2026.2.3 sources and HACS's code).
- Brand icon `custom_components/<domain>/brand/icon.png` (256x256) and `icon@2x.png` (512x512), original artwork.
  Home Assistant uses it from 2026.3 on. Replace it with your final logo (same sizes, PNG, transparent background,
  no Home Assistant branding).
- GitHub workflows (linted with actionlint, **not yet run**): `tests.yml`, `validate.yml` (HACS action + hassfest),
  `docker.yml` (builds on pull requests, pushes to GHCR on a `v*` tag), `release.yml` (creates the GitHub release).
- `scripts/set_identity.py` (rename in one command, tested on a copy: tests, hassfest, release gate and the real
  Home Assistant end-to-end test all pass after renaming) and `scripts/release_check.py` (blocks while anything
  provisional remains).

## State of the repository

Pushed to <https://github.com/Melvilh/solarprio> (branch `main`) with its description and topics set. Workflows: `Tests`
(engine and runtime, Home Assistant integration), `Validate` (hassfest, HACS) and `Docker image` (builds on pull requests
and on tags, never run yet). The HACS action warns that the manifest has no `categories` (a warning, not a failure).
The `v0.1.0` tag and release are created once `Tests` and `Validate` pass on the commit to tag.

## You do

### 1. Choose the identity

Pick a **technical name** (becomes the Home Assistant domain, Python package and folder; lowercase letters, digits,
underscores) and a **display name** that turns into it when lowercased with underscores (`Helio Router` ->
`helio_router`), because Home Assistant derives entity ids from it.

Check before you commit to it:

- No Home Assistant core integration already uses the domain (`homeassistant/components/<name>` in
  <https://github.com/home-assistant/core>).
- The GitHub repository, PyPI project (if you ever publish the engine) and GHCR image names are free.
- No trademark conflict. In France, search the INPI database; consider filing the mark before communicating
  widely. The license does not cover the name or logo, and nothing here protects them for you.

### 2. Apply it

```bash
git status                      # must be clean
python scripts/set_identity.py --name <domain> --display "<Display Name>" --repo <owner>/<repo> --owner <owner>
git diff --stat                 # review
pytest && scripts/test_ha.sh
python scripts/release_check.py # must print "ready to release"
git add -A && git commit -m "Set project identity"
```

### 3. Fix the commit author

The local history is authored by a placeholder `dev` identity with an invalid e-mail address. Rewrite it with the name and e-mail you want to appear
publicly (GitHub offers a private `...@users.noreply.github.com` address) **before the first push**; pushed
history is hard to take back.

### 4. Create the GitHub repository

HACS requires a **public** GitHub repository with, in its settings:

- a **description** (shown in HACS),
- **topics** (for example `home-assistant`, `hacs`, `hacs-integration`, `solar`, `energy`, `pv-router`),
- **Issues enabled**,
- not archived.

Also enable *Settings > Security > Private vulnerability reporting* (referenced by `SECURITY.md`).

### 5. Push and let the workflows run

Push, then open the *Actions* tab. All of `Tests`, `Validate` (HACS and hassfest) and the Docker build on a pull
request should pass. These workflows have never run: expect to fix small things, and tell me what fails.

### 6. Release

```bash
git tag v0.1.0 && git push origin v0.1.0
```

`release.yml` checks the tag equals the version in `manifest.json`, runs the release gate and creates the GitHub
release (HACS wants a release, not only a tag). `docker.yml` pushes `ghcr.io/<owner>/<repo>`; set that package
to public in the GitHub package settings if you want others to pull it. The image build has never been run.

### 7. Test the install like a user

On a Home Assistant 2026.2 or later: HACS > Custom repositories > add the repository URL as *Integration*,
download, restart, add the integration, add one device of each type you own, and watch it with a low-risk load.

### 8. Optional: the HACS default list

Once the workflows pass and a release exists, you can submit the repository to
<https://github.com/hacs/default> (the `integration` file, alphabetical order). Conditions from the HACS
documentation: you must be the owner or a major contributor, the pull request must come from a personal
account (not an organisation), the HACS Action and hassfest must pass with no ignores, and review takes months.
Users can install through *Custom repositories* in the meantime.

## Not covered here

Selling hardware (CE marking, electrical safety, radio rules, product liability), company formation and
insurance, and legal advice on licensing a commercial offer. Get qualified advice for those.
