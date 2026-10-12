export ZSH="$HOME/.oh-my-zsh"
# The bootstrap updates ~/.oh-my-zsh. Do not let Oh My Zsh update itself.
zstyle ':omz:update' mode disabled
ZSH_THEME="robbyrussell"
plugins=(git)

if [[ -r "$ZSH/oh-my-zsh.sh" ]]; then
  source "$ZSH/oh-my-zsh.sh"
fi
