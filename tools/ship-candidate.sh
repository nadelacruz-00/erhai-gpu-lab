#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# One command from a kernel branch to a queued g0 run: export the branch as
# candidates/<candidate>/*.patch, commit and push when they changed, wait for
# the kernel workflow, fetch the build, queue g0. Run as the normal user from
# the lab repo; only fetch and queue use sudo. Refuses (exit 2) without an
# origin remote, with changes outside candidates/<candidate>/, or without gh.
set -euo pipefail

usage() { echo "usage: $0 <kernel-dir> <branch> <candidate> [--prefix N]" >&2; exit 2; }
die() { echo "$0: $*" >&2; exit 2; }

[ $# -ge 3 ] || usage
K=$1 BRANCH=$2 CAND=$3
shift 3
PREFIX=()
while [ $# -gt 0 ]; do
    case $1 in
        --prefix) [ $# -ge 2 ] || usage; PREFIX=(--prefix "$2"); shift 2 ;;
        *) usage ;;
    esac
done
case $CAND in ''|/*|*..*) usage ;; esac

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

git remote get-url origin >/dev/null 2>&1 \
    || die "no git remote; publish the lab repo first"
DIRTY=$(git status --porcelain --untracked-files=all -- . ":(exclude)candidates/$CAND")
[ -z "$DIRTY" ] || die "uncommitted changes outside candidates/$CAND/; commit or stash them first:
$DIRTY"
gh auth status >/dev/null 2>&1 || die "gh is not logged in; run: gh auth login"

bash "$ROOT/tools/export-patches.sh" "$K" "$BRANCH" "$CAND" ${PREFIX[@]+"${PREFIX[@]}"}

KSHA=$(tr -d '[:space:]' < "candidates/$CAND/STACK")
KSHA=${KSHA:0:12}
STATUS=()
if [ -n "$(git status --porcelain --untracked-files=all -- "candidates/$CAND")" ]; then
    git add -A -- "candidates/$CAND"
    git commit -q -m "candidates: $CAND from $BRANCH @$KSHA"
    if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
        git push
    else
        git push -u origin HEAD
    fi
else
    echo "patches unchanged; using the latest successful kernel run for HEAD"
    STATUS=(--status success)
fi

# The workflow run can take a moment to appear after the push: 13 tries, 10 s apart.
HEAD_SHA=$(git rev-parse HEAD)
RUN=
for attempt in $(seq 1 13); do
    RUN=$(gh run list --workflow kernel.yml --commit "$HEAD_SHA" ${STATUS[@]+"${STATUS[@]}"} \
        --json databaseId -q '.[0].databaseId' 2>/dev/null || true)
    case $RUN in ''|null) RUN= ;; *) break ;; esac
    [ "$attempt" -lt 13 ] || break
    echo "waiting for the kernel workflow run for ${HEAD_SHA:0:12}..."
    sleep 10
done
[ -n "$RUN" ] || { echo "$0: no kernel workflow run found for ${HEAD_SHA:0:12}" >&2; exit 1; }

gh run watch "$RUN" --exit-status

# kernel.yml tags the release lab-<candidate>-<run_number>: fetch this run's
# build, not whatever release of the candidate happens to be the latest.
N=$(gh run view "$RUN" --json number -q .number)
FETCH_OUT=$(mktemp)
trap 'rm -f "$FETCH_OUT"' EXIT
sudo erhai-gpu-lab fetch "$CAND" --tag "lab-$CAND-$N" | tee "$FETCH_OUT"
KVER=$(sed -n 's|^installed /boot/\(.*\)\.efi .*|\1|p' "$FETCH_OUT" | tail -n 1)
[ -n "$KVER" ] || KVER=lab-$CAND
sudo erhai-gpu-lab queue g0 --expect "$CAND"

echo "Reboot and pick $KVER in rEFInd; g0 runs by itself. Then: erhai-gpu-lab status"
