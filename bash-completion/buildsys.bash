# Bash completion adapter: candidate selection belongs to buildsys completion.
_buildsys_complete()
{
    local cur cword command count
    local -a words arguments
    COMPREPLY=()
    if declare -F _get_comp_words_by_ref >/dev/null; then
        _get_comp_words_by_ref -n : cur words cword || return 0
    else
        words=("${COMP_WORDS[@]}")
        cword=$COMP_CWORD
        cur=${words[cword]-}
    fi
    (( cword >= 1 )) || return 0
    command=${words[0]}
    count=$(( cword - 1 ))
    arguments=("${words[@]:1:count}" "$cur")
    mapfile -t COMPREPLY < <("$command" completion -- "${arguments[@]}" 2>/dev/null)
    if [[ ${words[1]-} == install ]]; then
        if (( cword == 2 )); then
            # Item names need the normal trailing space; directories still need quoting.
            compopt -o filenames 2>/dev/null || :
        elif (( cword == 3 )) && [[ ${words[2]-} == buildsys || ${words[2]-} == completion ]]; then
            compopt -o filenames -o nospace 2>/dev/null || :
        fi
    fi
}

complete -F _buildsys_complete buildsys buildsys.sh
# bash-completion's lazy loader may source this file for a command with a path.
case ${1-} in
    buildsys|buildsys.sh|*/buildsys|*/buildsys.sh)
        complete -F _buildsys_complete -- "$1"
        ;;
esac
