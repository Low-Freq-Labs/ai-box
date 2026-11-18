# Debian FREQ-AI-SETUP interactive shell identity.
case "$-" in
    *i*) ;;
    *) return 0 2>/dev/null || exit 0 ;;
esac

_fq_account="$(id -un 2>/dev/null)"
if [[ -f /etc/freq-ai-setup/site.conf \
      && "$(stat -Lc '%U:%G:%a' /etc/freq-ai-setup/site.conf 2>/dev/null)" == root:root:644 ]]; then
    source /etc/freq-ai-setup/site.conf
fi
_fq_identity="/etc/freq-ai-setup/identities/${_fq_account}.conf"
if [[ -f "$_fq_identity" ]]; then
    _fq_meta="$(stat -Lc '%U:%G:%a' "$_fq_identity" 2>/dev/null || true)"
    if [[ "$_fq_meta" == root:root:644 ]]; then
        # Root-owned files contain only validated, generated identity values.
        source "$_fq_identity"
    fi
fi
unset _fq_meta _fq_identity

if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx freq-agents; then
    umask 0002
    export FREQ_SANDBOX_EXPECTED=1
    export npm_config_prefix="$HOME/.local"
else
    umask 0022
fi

for _fq_bin in "$HOME/tools" "$HOME/bin" "$HOME/.local/bin"; do
    case ":$PATH:" in
        *":$_fq_bin:"*) ;;
        *) PATH="$_fq_bin:$PATH" ;;
    esac
done
_fq_refresh_agent_path() {
    local _fq_agent_bin
    for _fq_agent_bin in "$HOME"/agents/*; do
        [[ -d $_fq_agent_bin && ! -L $_fq_agent_bin ]] || continue
        case ":$PATH:" in
            *":$_fq_agent_bin:"*) ;;
            *) PATH="$_fq_agent_bin:$PATH" ;;
        esac
    done
    export PATH
}
_fq_refresh_agent_path

create-agent() {
    "$HOME/tools/create-agent" "$@"
    local _fq_status=$?
    (( _fq_status != 0 )) || _fq_refresh_agent_path
    return "$_fq_status"
}
export PATH
unset _fq_bin

export EDITOR="${EDITOR:-nano}"
export VISUAL="${VISUAL:-$EDITOR}"
export PAGER="${PAGER:-less}"
export LESS="${LESS:--FRX}"
export COLORTERM="${COLORTERM:-truecolor}"
export VIRTUAL_ENV_DISABLE_PROMPT=1

HISTCONTROL=ignoreboth:erasedups
HISTSIZE=50000
HISTFILESIZE=100000
shopt -s histappend cmdhist checkwinsize

alias ls='ls --color=auto'
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias grep='grep --color=auto'
command -v fdfind >/dev/null 2>&1 && alias fd='fdfind'
command -v batcat >/dev/null 2>&1 && alias bat='batcat'

if [[ -r /usr/local/share/freq-ai-setup/nexus-prompt.sh ]]; then
    source /usr/local/share/freq-ai-setup/nexus-prompt.sh
    PROMPT_COMMAND='_fq_refresh_agent_path; _fq_title; _fq_prompt; history -a; history -n'
fi
unset _fq_account
