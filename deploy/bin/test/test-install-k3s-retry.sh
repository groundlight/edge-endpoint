#!/usr/bin/env bash
# Network-free unit test for retry() in install-k3s.sh. Sources the script in
# lib-only mode, then drives retry() against a PATH stub whose failures we set.
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export INSTALL_K3S_LIB_ONLY=1
# shellcheck disable=SC1091
source "$DIR/../install-k3s.sh"
set +e   # drop the `set -e` inherited from the sourced script

# `flaky` on PATH: counts calls in $CNT, exits 1 for the first $FAIL_UNTIL calls.
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/flaky" <<'STUB'
#!/usr/bin/env bash
n=$(( $(cat "$CNT") + 1 )); echo "$n" > "$CNT"
[ "$n" -le "$FAIL_UNTIL" ] && exit 1 || exit 0
STUB
chmod +x "$tmp/flaky"
export PATH="$tmp:$PATH" CNT="$tmp/cnt"

fail=0
expect() { if [ "$2" = "$3" ]; then echo "PASS $1 ($2)"; else echo "FAIL $1: want $3, got $2"; fail=1; fi; }

# 1) Succeeds after transient failures: fail twice, succeed on the 3rd call.
export FAIL_UNTIL=2; echo 0 > "$CNT"
retry 3 0 -- flaky; rc=$?              # base_sleep 0 => no real delay
expect "succeeds: rc"    "$rc"          0
expect "succeeds: calls" "$(cat "$CNT")" 3

# 2) Gives up after max attempts: always fail, stop after exactly 3 attempts.
export FAIL_UNTIL=999; echo 0 > "$CNT"
retry 3 0 -- flaky; [ $? -ne 0 ] && nz=yes || nz=no
expect "gives-up: rc-nonzero" "$nz"          yes
expect "gives-up: calls"      "$(cat "$CNT")" 3

echo
[ "$fail" -eq 0 ] && echo "All tests passed." || echo "Some tests FAILED."
exit "$fail"
