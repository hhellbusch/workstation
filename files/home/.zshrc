export ZSH="$HOME/.oh-my-zsh"
# The bootstrap updates ~/.oh-my-zsh. Do not let Oh My Zsh update itself.
zstyle ':omz:update' mode disabled
# Kept outside the Oh My Zsh checkout so an update does not remove it.
ZSH_CUSTOM="$HOME/.config/oh-my-zsh"
ZSH_THEME="amuse-hank"
plugins=(git)

if [[ -r "$ZSH/oh-my-zsh.sh" ]]; then
  source "$ZSH/oh-my-zsh.sh"
fi
