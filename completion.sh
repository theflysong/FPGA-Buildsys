#!/usr/bin/env bash
# Read completion metadata without configuring or executing a project task.
set -euo pipefail
shopt -s nullglob

project_dir=$1
shift
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${1-} == -- ]]; then
    shift
fi
words=("$@")
if (( ${#words[@]} == 0 )); then
    words=("")
fi
position=$(( ${#words[@]} - 1 ))
prefix=${words[position]}
declare -A emitted=()

emit() {
    local candidate=$1
    if [[ $candidate == "$prefix"* && ! ${emitted[$candidate]+present} ]]; then
        printf '%s\n' "$candidate"
        emitted[$candidate]=1
    fi
}

target_ids() {
    local extension file identifier found kind
    for extension in "$@"; do
        found=0
        for file in "$project_dir/build/aux/"*"$extension"; do
            [[ -f $file ]] || continue
            identifier=${file##*/}
            identifier=${identifier%"$extension"}
            [[ $identifier =~ ^[A-Za-z][A-Za-z0-9_-]*$ ]] || continue
            found=1
            emit "$identifier"
        done
        if (( found == 0 )); then
            if [[ $extension == .f ]]; then kind=simulation; else kind=program; fi
            while IFS= read -r identifier; do
                emit "$identifier"
            done < <(python3 "$script_dir/completion_ids.py" "$project_dir/configuration.toml" "$kind" 2>/dev/null)
        fi
    done
}

directories() {
    local directory
    while IFS= read -r directory; do
        emit "${directory%/}/"
    done < <(compgen -d -- "$prefix")
}

if (( position == 0 )); then
    for command in aux script build simulate synthesis implementation bitstream program clean cleandist init install completion; do
        emit "$command"
    done
    exit 0
fi

case ${words[0]} in
    build|simulate)
        if (( position == 1 )); then target_ids .f; fi
        ;;
    synthesis|implementation|bitstream)
        if (( position == 1 )); then target_ids .ys; fi
        ;;
    clean|cleandist)
        if (( position == 1 )); then target_ids .f .ys; fi
        ;;
    install)
        if (( position == 1 )); then
            emit buildsys
            emit completion
            directories
        elif (( position == 2 )) && [[ ${words[1]} == buildsys || ${words[1]} == completion ]]; then
            directories
        fi
        ;;
    program)
        declare -A supplied=()
        expecting_value=""
        target_seen=0
        # Parse complete words only; the final word is the prefix being completed.
        for (( index=1; index<position; index++ )); do
            word=${words[index]}
            if [[ -n $expecting_value ]]; then
                expecting_value=""
                continue
            fi
            case $word in
                --protocol|--busdev-num|--ftdi-serial)
                    supplied[$word]=1
                    expecting_value=$word
                    ;;
                --protocol=*|--busdev-num=*|--ftdi-serial=*)
                    supplied[${word%%=*}]=1
                    ;;
                -*) exit 0 ;;
                *)
                    (( target_seen == 0 )) || exit 0
                    target_seen=1
                    ;;
            esac
        done
        # Protocol and device values are explicitly supplied; Tab does not probe USB.
        [[ -z $expecting_value ]] || exit 0
        if (( target_seen == 0 )) && [[ $prefix != -* ]]; then
            target_ids .ys
        else
            for option in --protocol --busdev-num --ftdi-serial; do
                [[ ! ${supplied[$option]+present} ]] || continue
                if [[ $option == --busdev-num && ${supplied[--ftdi-serial]+present} ||
                      $option == --ftdi-serial && ${supplied[--busdev-num]+present} ]]; then
                    continue
                fi
                emit "$option"
            done
        fi
        ;;
esac
exit 0
