# workstation

A profile-based bootstrap for a Fedora machine. One public repo describes the tools and settings. A private overlay, when you have one, adds anything that should not be published.

A fresh checkout applies the `base` profile unless `PROFILES` or `~/.config/workstation/machine.env` selects others.

## Layout on disk

Checkouts follow the remote they came from:

```text
~/git/public/github.com/<owner>/<repo>
~/git/private/github.com/<owner>/<repo>
~/git/private/customers/<customer>/<repo>
```

This repo is the public workstation bootstrap, so its path is `~/git/public/github.com/hhellbusch/workstation`.

## Profiles

Pass a comma-separated list. Each name is a file in `profiles/`.

| Profile | Use |
|---|---|
| `base` | Every machine. Shell, git, editor, settings you want everywhere. |
| `work` | OpenShift, Argo CD, Tekton, Buildah, Ansible, and the public field-notes repo. |
| `ai` | Local model inference. |
| `gaming` | Steam and related desktop tools. Cluster CLIs stay out of this profile. |
| `laptop` | Touchpad, display scale, and AC versus battery power. |

```bash
PROFILES=base,work,laptop ./bootstrap.sh
```

To make that the default on one machine, copy `machine.example.env` to `~/.config/workstation/machine.env`. A `PROFILES` value in the environment wins over that file.

## What stays private

Corporate hosts, Kerberos git configuration, and anything specific to a managed build belong in a private checkout:

```text
~/git/private/github.com/hhellbusch/workstation/overlay.yml
```

`overlay.yml` is an Ansible task file. The bootstrap includes it after the public profiles when the file exists. Set `WORKSTATION_PRIVATE` to point somewhere else. The public repo does not need that file, and it does not create it.

## Supply chain

1. Install from Fedora when Fedora ships the package. Add the package name to a profile.
2. For anything else, add an entry to `lockfile.yml` with the exact URL and `sha256`, and name that entry from a profile. The bootstrap refuses a download whose digest does not match.
3. Do not add installers that pipe a downloaded script into a shell.

`kind: file` means the URL is the executable. `kind: archive` means the URL is a tarball or zip, and `source_path` is the file to copy out of it. Installed binaries land in `~/.local/bin`.

## Adding something

Fedora package, in the profile that should own it:

```yaml
packages:
  - buildah
```

Package group, without the `@` prefix:

```yaml
groups:
  - kde-desktop
```

Pinned binary: an entry in `lockfile.yml`, then the key in the profile:

```yaml
binaries:
  - oc
```

Dotfile: put the file under `files/home/` using the path it should have in the home directory, then list that path:

```yaml
dotfiles:
  - .gitconfig
```

GNOME setting. `value` is the text `gsettings get` prints. Booleans are `true` or `false`. A string includes the single quotes that `gsettings` expects, such as `"'prefer-dark'"`. An optional `notice` is printed at the end of the play, and only when that setting changed.

```yaml
gsettings:
  - schema: org.gnome.desktop.peripherals.touchpad
    key: natural-scroll
    value: "false"
```

Public git clone. `dest` is relative to your home directory and follows the directory layout above. Profile files are plain YAML, so write the path out rather than using a template.

```yaml
repos:
  - url: https://github.com/hhellbusch/my-ai-workspace.git
    dest: git/public/github.com/hhellbusch/my-ai-workspace
    version: main
    submodules: true
```

Package and group tasks use `sudo`. Binary, dotfile, Flatpak, GNOME settings, user services, and git tasks run as you. Firefox settings are written to each profile as `user.js`: a blank page for new tabs and new windows, strict tracking protection, and Firefox's password manager turned off. Pinned Firefox extensions are copied into the profile from `lockfile.yml`. The lockfile is limited to add-ons Mozilla recommends or publishes as By Firefox. An extension that is already installed is left in place. When Firefox is not running, bookmarks that match a system skeleton `bookmarks.html` are removed. The base profile copies Cursor `settings.json` and `keybindings.json`. Ctrl+Enter sends a chat message, because Cursor stores that choice in its state database rather than in `settings.json`. Quit Cursor first when it is already open. A user service is a systemd unit under `files/home/.config/systemd/user/`, named from the profile:

```yaml
user_services:
  - workstation-power-profile.service
```

## Running

```bash
./bootstrap.sh
./bootstrap.sh --check
```

Extra arguments are passed through to `ansible-playbook`. Package and group installs use `sudo`, and so does the Fedora update check. That check does not install updates. When updates are available, the play says so in the final follow-up list.

## License

Apache License 2.0. See [LICENSE](LICENSE).
