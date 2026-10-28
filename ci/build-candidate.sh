#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Build one lab candidate kernel from the pinned erhai tree and stage its
# release assets in out/<candidate>/:
#
#   <kernelrelease>.efi              UKI: arch/arm64/boot/Image + erhai.dtb +
#                                    the candidate's cmdline, assembled with
#                                    ukify the way the tree's postinst does it
#   modules-<kernelrelease>.tar.zst  lib/modules/<kernelrelease>/, stripped,
#                                    unpacked into /usr/lib/modules/ on the tablet
#   config-<kernelrelease>           the final .config
#   SHA256SUMS                       sha256 of every file above
#
#   ci/build-candidate.sh <candidate> [<build-id>]
#
# The kernel itself is built by the tree's own build-kernel.sh, so a lab kernel
# differs from the dev's only by the candidate's patches, its extra.config and
# the -lab-<candidate> LOCALVERSION suffix (own kernelrelease, own modules dir,
# never the installed package's).
set -euo pipefail

CAND=${1:?usage: build-candidate.sh <candidate> [<build-id>]}
BUILD_ID=${2:-local}

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
CDIR=$REPO_ROOT/candidates/$CAND
KERNEL_REPO=${KERNEL_REPO:-https://github.com/TheMojoMan/oneplus-erhai-linux.git}
BASE_SHA=$(tr -d '[:space:]' < "$REPO_ROOT/candidates/BASE_SHA")
WORK=${WORK:-$REPO_ROOT/work}
TREE=$WORK/linux
OUT=$REPO_ROOT/out/$CAND
JOBS=${JOBS:-$(nproc)}

[ -d "$CDIR" ] || { echo "no candidate dir $CDIR" >&2; exit 1; }
[ -f "$CDIR/cmdline" ] || { echo "candidate $CAND has no cmdline" >&2; exit 1; }
shopt -s nullglob
PATCHES=("$CDIR"/*.patch)
shopt -u nullglob
if [ -f "$CDIR/STACK" ] && [ ${#PATCHES[@]} -eq 0 ]; then
	echo "candidate $CAND: STACK present but no patches" >&2
	exit 1
fi

CMDLINE="$(tr -s '[:space:]' ' ' < "$CDIR/cmdline" | sed 's/^ //; s/ $//') erhai_lab.candidate=$CAND erhai_lab.build=$BUILD_ID"
if [ -f "$CDIR/STACK" ]; then
	CMDLINE="$CMDLINE erhai_lab.stack=$(head -c12 "$CDIR/STACK")"
fi
# Test seam: validate the candidate and print the UKI cmdline, build nothing.
if [ "${PRINT_CMDLINE:-}" = 1 ]; then
	echo "$CMDLINE"
	exit 0
fi

# ------------------------------------------------------------------ source ---
if [ ! -d "$TREE/.git" ]; then
	git init -q "$TREE"
	git -C "$TREE" remote add origin "$KERNEL_REPO"
fi
echo "fetching $KERNEL_REPO @ $BASE_SHA"
git -C "$TREE" fetch -q --depth 1 origin "$BASE_SHA"
git -C "$TREE" checkout -q --force FETCH_HEAD

# The tree's build-kernel.sh applies $TREE/patches/*.patch and merges
# $TREE/kernel-build-files/extra.config; stage the candidate's into both.
rm -rf "$TREE/patches" "$TREE/kernel-build-files"
mkdir -p "$TREE/patches" "$TREE/kernel-build-files"
for p in "${PATCHES[@]}"; do cp "$p" "$TREE/patches/"; done
if [ -f "$CDIR/extra.config" ]; then
	cp "$CDIR/extra.config" "$TREE/kernel-build-files/extra.config"
fi

# ------------------------------------------------------------------- build ---
# scripts/setlocalversion appends "+" to the kernelrelease when the tree is a
# git checkout off a release tag and LOCALVERSION is unset. Set it (empty) so
# the release is exactly <base>-sm8750-themojoman-lab-<candidate>.
export LOCALVERSION=
# DEB_REV is fixed: the .deb the tree script packs is discarded, a lab kernel
# is never installed with dpkg (it would replace the package's modules).
(cd "$TREE" && PKG_SUFFIX="-lab-$CAND" DEB_REV=1 JOBS="$JOBS" ./build-kernel.sh)
rm -f "$TREE"/oneplus-erhai-linux-*_arm64.deb

KVER=$(make -s -C "$TREE" ARCH=arm64 kernelrelease)
echo "kernelrelease: $KVER"
case "$KVER" in
*-lab-"$CAND") ;;
*) echo "kernelrelease $KVER does not carry -lab-$CAND" >&2; exit 1 ;;
esac

if [ -f "$CDIR/extra.config" ]; then
	"$REPO_ROOT/ci/assert-config.sh" "$CDIR/extra.config" "$TREE/.config"
fi

# ----------------------------------------------------------------- staging ---
rm -rf "$OUT"
mkdir -p "$OUT"
STAGE=$WORK/stage-$CAND
rm -rf "$STAGE"
make -s -C "$TREE" ARCH=arm64 -j"$JOBS" INSTALL_MOD_PATH="$STAGE" \
	INSTALL_MOD_STRIP=1 modules_install
MODDIR=$STAGE/lib/modules/$KVER
rm -f "$MODDIR/build" "$MODDIR/source"
# The WCN stack (cnss2 + qcacld wlan.ko) is built in-tree by the defconfig;
# a test kernel without it has no Wi-Fi and cannot run the Wi-Fi rungs.
for m in wlan.ko cnss2.ko; do
	if [ -z "$(find "$MODDIR" -name "$m" -print -quit)" ]; then
		echo "$m missing from $MODDIR" >&2
		exit 1
	fi
done
tar -C "$STAGE/lib/modules" --owner=0 --group=0 -c "$KVER" |
	zstd -q -T0 -19 -o "$OUT/modules-$KVER.tar.zst"

cp "$TREE/.config" "$OUT/config-$KVER"

ukify build \
	--linux "$TREE/arch/arm64/boot/Image" \
	--devicetree "$TREE/arch/arm64/boot/dts/qcom/erhai.dtb" \
	--efi-arch aa64 \
	--uname "$KVER" \
	--cmdline "$CMDLINE" \
	--output "$OUT/$KVER.efi"

(cd "$OUT" && sha256sum -- * > SHA256SUMS)
echo "staged:"
ls -la "$OUT"
cat "$OUT/SHA256SUMS"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
	echo "kver=$KVER" >> "$GITHUB_OUTPUT"
	echo "patches=${#PATCHES[@]}" >> "$GITHUB_OUTPUT"
fi
