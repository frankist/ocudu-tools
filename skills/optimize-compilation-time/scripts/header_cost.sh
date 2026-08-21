#!/usr/bin/env bash
# Marginal compile cost of one or more headers: time to compile a TU that
# includes only that header, minus an empty TU. Multiply by the number of
# affected TUs (divided by build parallelism) for the ceiling on any change
# that removes it from an include graph.
#
#   header_cost.sh complex sstream functional vector
#   header_cost.sh --std gnu++20 --flags '-O2 -march=native' complex
set -euo pipefail

STD=gnu++17
FLAGS=-O2
REPS=5
while [[ ${1:-} == --* ]]; do
  case $1 in
    --std)   STD=$2;   shift 2 ;;
    --flags) FLAGS=$2; shift 2 ;;
    --reps)  REPS=$2;  shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[[ $# -gt 0 ]] || { echo "usage: $(basename "$0") [--std S] [--flags F] [--reps N] <header>..." >&2; exit 2; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# shellcheck disable=SC2086
best_of() {
  local src=$1 best=999
  for _ in $(seq "$REPS"); do
    local t0 t1
    t0=$(date +%s.%N)
    ${CXX:-c++} -std="$STD" $FLAGS -c "$src" -o "$tmp/out.o"
    t1=$(date +%s.%N)
    best=$(python3 -c "print(min($best, $t1 - $t0))")
  done
  echo "$best"
}

printf 'int main(){}\n' > "$tmp/empty.cpp"
baseline=$(best_of "$tmp/empty.cpp")
printf 'empty TU baseline: %.3fs (std=%s flags=%s)\n\n' "$baseline" "$STD" "$FLAGS"

for hdr in "$@"; do
  printf '#include <%s>\nint main(){}\n' "$hdr" > "$tmp/h.cpp"
  total=$(best_of "$tmp/h.cpp")
  python3 -c "print(f'<$hdr>'.ljust(24) + f'{$total - $baseline:6.3f}s marginal')"
done
