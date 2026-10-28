#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Regenerate candidates/<candidate>/*.patch from BASE_SHA..<branch> of a kernel
# checkout, so CI builds exactly what the branch holds. Records the tip in STACK.
set -euo pipefail

usage() { echo "usage: $0 <kernel-dir> <branch> <candidate> [--prefix N]" >&2; exit 64; }

[ $# -ge 3 ] || usage
K=$1 BRANCH=$2 CAND=$3
shift 3
PREFIX=
while [ $# -gt 0 ]; do
    case $1 in
        --prefix) [ $# -ge 2 ] || usage; PREFIX=$2; shift 2 ;;
        *) usage ;;
    esac
done
case $PREFIX in ''|*[!0-9]*) [ -z "$PREFIX" ] || usage ;; esac

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE=$(tr -d '[:space:]' < "$ROOT/candidates/BASE_SHA")

git -C "$K" rev-parse --git-dir >/dev/null 2>&1 \
    || { echo "$K is not a git repository" >&2; exit 2; }
git -C "$K" rev-parse --verify -q "$BRANCH^{commit}" >/dev/null \
    || { echo "$BRANCH: unknown revision in $K" >&2; exit 2; }
git -C "$K" merge-base --is-ancestor "$BASE" "$BRANCH" \
    || { echo "$BRANCH is not a descendant of BASE_SHA $BASE" >&2; exit 2; }

END=$BRANCH
if [ -n "$PREFIX" ]; then
    COUNT=$(git -C "$K" rev-list --count "$BASE..$BRANCH")
    [ "$PREFIX" -le "$COUNT" ] \
        || { echo "--prefix $PREFIX exceeds the $COUNT commits above BASE_SHA" >&2; exit 2; }
    END="$BRANCH~$((COUNT - PREFIX))"
fi

OUT="$ROOT/candidates/$CAND"
mkdir -p "$OUT"
# Stage next to the destination (same filesystem), then swap in, so a failure
# leaves the existing patches and STACK intact.
TMP=$(mktemp -d "$ROOT/candidates/.export.XXXXXX")
trap 'rm -rf "$TMP" "$TMP.list"' EXIT
# Fixed prefixes: user diff.noprefix / diff.mnemonicPrefix must not change what `patch -p1` sees.
git -C "$K" -c diff.noprefix=false -c diff.mnemonicPrefix=false format-patch \
    --src-prefix=a/ --dst-prefix=b/ --zero-commit --no-signature --no-numbered \
    -o "$TMP/" "$BASE..$END" > "$TMP.list"
git -C "$K" rev-parse "$END" > "$TMP/STACK"
rm -f "$OUT"/*.patch
mv "$TMP"/* "$OUT"/
sed "s|^$TMP/|$OUT/|" "$TMP.list"
