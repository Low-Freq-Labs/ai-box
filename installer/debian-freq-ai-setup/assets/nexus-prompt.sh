# Shared Bash port of Sonny's canonical MacBook NEXUS prompt.
# Only the username and input arrow vary by FREQ-AI-SETUP user.

# ── identity ────────────────────────────────────────────────────────────
: "${FREQ_USER:=$(id -un)}"
: "${FREQ_HOST:=WSL}"
: "${FREQ_TITLE:=N  E  X  U  S}"
: "${FREQ_SUBTITLE:=LOW FREQ Labs}"
: "${FREQ_WIDTH:=59}"

# ── palette ─────────────────────────────────────────────────────────────
if [[ "$COLORTERM" == "truecolor" || "$COLORTERM" == "24bit" ]]; then
    FQ_PRIMARY=$'\e[38;2;168;85;247m'
    FQ_ACCENT=$'\e[38;2;168;85;247m'
    FQ_DARK=$'\e[38;2;190;190;190m'

    if [[ ${FREQ_USER_TRUECOLOR:-} =~ ^[0-9]+\;[0-9]+\;[0-9]+$ ]]; then
        FQ_USER=$'\e[38;2;'"${FREQ_USER_TRUECOLOR}"'m'
    else
        case "$FREQ_USER" in
            finn)   FQ_USER=$'\e[38;2;56;189;248m' ;;
            jarvis) FQ_USER=$'\e[38;2;251;146;60m' ;;
            clancy) FQ_USER=$'\e[38;2;244;114;182m' ;;
            *)      FQ_USER=$'\e[38;2;168;85;247m' ;;
        esac
    fi
else
    FQ_PRIMARY=$'\e[38;5;141m'
    FQ_ACCENT=$'\e[38;5;141m'
    FQ_DARK=$'\e[38;5;250m'

    if [[ ${FREQ_USER_256:-} =~ ^[0-9]+$ ]]; then
        FQ_USER=$'\e[38;5;'"${FREQ_USER_256}"'m'
    else
        case "$FREQ_USER" in
            finn)   FQ_USER=$'\e[38;5;45m' ;;
            jarvis) FQ_USER=$'\e[38;5;208m' ;;
            clancy) FQ_USER=$'\e[38;5;205m' ;;
            *)      FQ_USER=$'\e[38;5;141m' ;;
        esac
    fi
fi

FQ_DIM=$'\e[38;5;244m'
FQ_WHITE=$'\e[38;5;231m'
FQ_ERR=$'\e[38;5;203m'
FQ_BOLD=$'\e[1m'
FQ_RESET=$'\e[0m'

# ── helpers ─────────────────────────────────────────────────────────────
_fq_unit() {
    if (( $1 == 1 )); then
        printf '%s %s' "$1" "$2"
    else
        printf '%s %ss' "$1" "$2"
    fi
}

_fq_uptime() {
    local secs

    if [[ -r /proc/uptime ]]; then
        read -r secs _ < /proc/uptime
        secs=${secs%%.*}
    else
        secs=${SECONDS:-0}
    fi

    [[ "$secs" =~ ^[0-9]+$ ]] || {
        printf 'unknown'
        return
    }

    local w=$(( secs / 604800 ))
    local d=$(( (secs % 604800) / 86400 ))
    local h=$(( (secs % 86400) / 3600 ))
    local m=$(( (secs % 3600) / 60 ))

    local -a p=()

    (( w )) && p+=("$(_fq_unit "$w" week)")
    (( w || d )) && p+=("$(_fq_unit "$d" day)")
    (( w || d || h )) && p+=("$(_fq_unit "$h" hour)")
    p+=("$(_fq_unit "$m" minute)")

    local out=""
    local item

    for item in "${p[@]}"; do
        [[ -n "$out" ]] && out+=", "
        out+="$item"
    done

    printf '%s' "$out"
}

_fq_center() {
    local colour=$1
    local text=$2
    local pad=$(( (FREQ_WIDTH - ${#text}) / 2 ))

    (( pad < 0 )) && pad=0

    printf '%*s' "$pad" ''
    printf '%s%s%s\n' "$colour" "$text" "$FQ_RESET"
}

_fq_center_orn() {
    local orn=$1
    local gap=$2
    local text=$3
    local tcol=$4
    local ocol=${5:-$FQ_DIM}

    local plain="${orn}${gap}${text}${gap}${orn}"
    local pad=$(( (FREQ_WIDTH - ${#plain}) / 2 ))

    (( pad < 0 )) && pad=0

    printf '%*s' "$pad" ''
    printf '%s%s%s%s%s%s%s%s%s\n' \
        "$ocol" \
        "$orn" \
        "$FQ_RESET" \
        "$gap" \
        "$tcol" \
        "$text" \
        "$FQ_RESET" \
        "$gap" \
        "${ocol}${orn}${FQ_RESET}"
}

_fq_center_kv() {
    local label=$1
    local value=$2
    local gap='     '

    local plain="${label}${gap}${value}"
    local pad=$(( (FREQ_WIDTH - ${#plain}) / 2 ))

    (( pad < 0 )) && pad=0

    printf '%*s' "$pad" ''
    printf '%s%s%s%s%s%s\n' \
        "$FQ_DIM" \
        "$label" \
        "$gap" \
        "$FQ_WHITE" \
        "$value" \
        "$FQ_RESET"
}

_fq_rule() {
    printf '  %s' "$FQ_DARK"
    printf '═%.0s' {1..55}
    printf '%s\n' "$FQ_RESET"
}

# ── banner ──────────────────────────────────────────────────────────────
freq_banner() {
    printf '\n'

    _fq_rule

    printf '\n'

    _fq_center_orn \
        '◆◆◆◆◆' \
        '   ' \
        "$FREQ_TITLE" \
        "${FQ_WHITE}${FQ_BOLD}" \
        "$FQ_ACCENT"

    printf '\n'

    _fq_center_orn \
        '~  ∿  ~  ∿  ~' \
        '  ' \
        "$FREQ_SUBTITLE" \
        "$FQ_WHITE" \
        "$FQ_PRIMARY"

    printf '\n'

    _fq_rule

    printf '\n'

    _fq_center_kv \
        'UPTIME' \
        "$(_fq_uptime)"

    printf '\n'

    _fq_rule

    printf '\n'
}

# ── Git ─────────────────────────────────────────────────────────────────
_fq_git() {
    command git rev-parse --is-inside-work-tree &>/dev/null || return

    local ref

    ref=$(command git symbolic-ref --quiet --short HEAD 2>/dev/null) \
        || ref=$(command git rev-parse --short HEAD 2>/dev/null) \
        || return

    local dirty=''

    command git diff \
        --no-ext-diff \
        --quiet \
        --ignore-submodules \
        HEAD &>/dev/null || dirty='*'

    printf '  \\[%s\\]⑂ \\[%s\\]%s\\[%s\\]%s' \
        "$FQ_DIM" \
        "$FQ_PRIMARY" \
        "$ref" \
        "$FQ_ACCENT" \
        "$dirty"
}

# ── Python environment ──────────────────────────────────────────────────
export VIRTUAL_ENV_DISABLE_PROMPT=1

_fq_venv() {
    local name=''

    if [[ -n "$VIRTUAL_ENV" ]]; then
        name=${VIRTUAL_ENV##*/}

        if [[ "$name" == ".venv" || \
              "$name" == "venv"  || \
              "$name" == "env"   || \
              "$name" == ".env" ]]; then

            local parent=${VIRTUAL_ENV%/*}
            name=${parent##*/}
        fi

    elif [[ -n "$CONDA_DEFAULT_ENV" ]]; then
        name=$CONDA_DEFAULT_ENV

    else
        return
    fi

    printf '  \\[%s\\]◈ \\[%s\\]%s' \
        "$FQ_DIM" \
        "$FQ_PRIMARY" \
        "$name"
}

# ── Node ────────────────────────────────────────────────────────────────
_fq_node() {
    local dir="$PWD"

    while [[ "$dir" != "/" && \
             ! -f "$dir/package.json" && \
             ! -f "$dir/.nvmrc" ]]; do

        dir=${dir%/*}
        [[ -z "$dir" ]] && dir='/'
    done

    [[ -f "$dir/package.json" || -f "$dir/.nvmrc" ]] || return

    local v=''

    if [[ "$PATH" == *"/.nvm/versions/node/"* ]]; then
        v=${PATH#*/.nvm/versions/node/}
        v=${v%%/*}
    else
        v=$(command node --version 2>/dev/null) || return
    fi

    [[ -n "$v" ]] || return

    printf '  \\[%s\\]⬢ \\[%s\\]%s' \
        "$FQ_DIM" \
        "$FQ_PRIMARY" \
        "${v#v}"
}

# ── window/tab title ────────────────────────────────────────────────────
_fq_title() {
    local dir="$PWD"

    if [[ "$dir" == "$HOME"* ]]; then
        dir="~${dir#$HOME}"
    fi

    printf '\033]0;%s · %s\007' "$FREQ_USER" "$dir"
}

# ── prompt ──────────────────────────────────────────────────────────────
_fq_prompt() {
    local git=''
    local venv=''
    local node=''

    git=$(_fq_git)
    venv=$(_fq_venv)
    node=$(_fq_node)

    PS1="\[$FQ_DARK\]┌─ \[$FQ_WHITE\]◆ \[$FQ_BOLD$FQ_USER\]${FREQ_USER}\[$FQ_RESET$FQ_DIM\] · \[$FQ_WHITE\]${FREQ_HOST}\[$FQ_DIM\] : \[$FQ_ACCENT\]\w${git}${venv}${node}\[$FQ_RESET\]
\[$FQ_DARK\]└─\[$FQ_USER\]▸\[$FQ_RESET\] "
}

PROMPT_COMMAND='_fq_title; _fq_prompt'

# Build prompt immediately.
_fq_prompt

# ── show banner only on top-level interactive shells ────────────────────
if [[ $- == *i* \
      && -z "$FREQ_NO_BANNER" \
      && -z "$FREQ_BANNER_SHOWN" \
      && ${SHLVL:-1} -eq 1 \
      && -z "$CLAUDE_CODE_ENTRYPOINT" \
      && -z "$VSCODE_INJECTION" \
      && -z "$INSIDE_EMACS" ]]; then

    export FREQ_BANNER_SHOWN=1
    freq_banner
fi
