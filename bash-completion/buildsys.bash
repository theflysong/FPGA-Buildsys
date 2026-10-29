# Bash completion adapter: candidate selection belongs to buildsys completion.
_buildsys_complete()
{
    local cur cword command count word pending_equal=0
    local -a words arguments
    COMPREPLY=()
    if declare -F _get_comp_words_by_ref >/dev/null; then
        _get_comp_words_by_ref -n := cur words cword || return 0
    else
        words=("${COMP_WORDS[@]}")
        cword=$COMP_CWORD
        cur=${words[cword]-}
    fi
    (( cword >= 1 )) || return 0
    command=${words[0]}
    count=$(( cword - 1 ))
    # Readline splits '=' into separate words without bash-completion as well.
    for word in "${words[@]:1:count}" "$cur"; do
        if [[ $word == = && ${#arguments[@]} -gt 0 ]]; then
            arguments[${#arguments[@]}-1]+='='
            pending_equal=1
        elif (( pending_equal )); then
            arguments[${#arguments[@]}-1]+=$word
            pending_equal=0
        else
            arguments+=("$word")
        fi
    done
    cur=${arguments[${#arguments[@]}-1]}
    mapfile -t COMPREPLY < <("$command" completion -- "${arguments[@]}" 2>/dev/null)
    if [[ $cur == --terminal=* && $COMP_WORDBREAKS == *=* ]]; then
        COMPREPLY=("${COMPREPLY[@]#--terminal=}")
    fi
    if [[ ${arguments[0]-} == install ]]; then
        for word in "${COMPREPLY[@]}"; do
            if [[ $word == */ ]]; then
                compopt -o filenames 2>/dev/null || :
                break
            fi
        done
    fi
}

complete -F _buildsys_complete buildsys buildsys.sh
# bash-completion's lazy loader may source this file for a command with a path.
case ${1-} in
    buildsys|buildsys.sh|*/buildsys|*/buildsys.sh)
        complete -F _buildsys_complete -- "$1"
        ;;
esac
