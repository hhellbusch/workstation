#!/usr/bin/env bash
# Apply the workstation profiles selected by PROFILES or by
# ~/.config/workstation/machine.env. Extra arguments are passed to ansible-playbook.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
env_file="${config_home}/workstation/machine.env"

if [[ -z "${PROFILES:-}" && -f "${env_file}" ]]; then
  # shellcheck disable=SC1090
  source "${env_file}"
fi

export PROFILES="${PROFILES:-base}"

cd "${root}"
exec ansible-playbook playbook.yml "$@"
