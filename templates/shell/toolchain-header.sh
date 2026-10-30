TOOLCHAIN_ROOTS=($(roots))
toolchain_path=""
for toolchain_root in "${TOOLCHAIN_ROOTS[@]}"; do
  [[ -d "$toolchain_root" ]] || { printf "Missing toolchain root: %s\n" "$toolchain_root" >&2; exit 2; }
  toolchain_path+="$toolchain_root:$toolchain_root/bin:"
done
export PATH="${toolchain_path}$PATH"
