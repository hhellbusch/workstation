# Interactive terminals start zsh. The account shell stays bash.
if [[ $- == *i* && -t 1 && -z "${ZSH_VERSION:-}" ]] && command -v zsh >/dev/null; then
  export SHELL="$(command -v zsh)"
  exec zsh
fi
