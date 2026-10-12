export ZSH="$HOME/.oh-my-zsh"
# Stay on the commit recorded in profiles/base.yml.
zstyle ':omz:update' mode disabled
ZSH_THEME="robbyrussell"
plugins=(git)

if [[ -r "$ZSH/oh-my-zsh.sh" ]]; then
  source "$ZSH/oh-my-zsh.sh"
fi
