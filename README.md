# erhai-gpu-lab

A test lab for the GPU on the OnePlus Pad 3 (`erhai`, Snapdragon 8 Elite /
SM8750) running Ubuntu on the mainline port at
[TheMojoMan/oneplus-erhai-linux](https://github.com/TheMojoMan/oneplus-erhai-linux).

On that port the Adreno 830 GMU wedges and the GPU freezes under runtime PM.
The lab tests the reference stack against two device-tree windows for the GMU
(the port's and yzddmr6's), one candidate kernel per hypothesis, each with the
numbers it must produce. Candidate `60-gpu-reference` carries the reference
stack; only a candidate that passes its rung becomes a PR to the port.

## How it works

- **CI** (`.github/workflows/kernel.yml`) builds each directory under
  `candidates/` from the pinned commit in `candidates/BASE_SHA` (or the
  candidate's own `BASE_SHA`, recorded with `export-patches.sh --base`), with the
  tree's own `build-kernel.sh`, the candidate's patches and `extra.config`,
  and a `-lab-<candidate>` kernelrelease. Every requested config symbol is
  asserted in the final `.config`. The result is a Release: a UKI, a modules
  tarball, the `.config` and `SHA256SUMS`.
- **`erhai-gpu-lab`** (`tablet/erhai-lab`, stdlib-only python3; `sudo
  tablet/install.sh` installs it as `/usr/local/sbin/erhai-gpu-lab`) runs on the
  tablet. `erhai-gpu-lab fetch 60-gpu-reference` downloads a release, verifies every
  checksum and the UKI/modules version match, and installs the kernel beside
  the package kernel. The kernel is always picked by hand in rEFInd; the default
  entry is never changed. `sudo erhai-gpu-lab setup` installs the g1 tools and
  builds IGT `msm_recovery`; `erhai-gpu-lab status` shows the booted candidate,
  the pin mode, the queued g0 and recent boots; `erhai-gpu-lab report [--out
  FILE]` prints Markdown of all evidence (run it with sudo to include the soak
  wedge lines). `whoami`, `status`, `soak status` and `report` need no root;
  every other subcommand runs with sudo. The commands per rung are in the
  ladder's Runbook.
- **`tools/build-local.sh <candidate>`** builds a candidate on the tablet exactly
  as CI does, from the local kernel checkout (`--kernel-dir`, default
  `~/Development/oneplus-erhai-linux`), with a live progress line every 2 s
  (phase, objects/ETA, hottest CPU, clocks, thermal clamp). Install the result
  with `sudo erhai-gpu-lab fetch <candidate> --from-dir out/<candidate>`.
  Build times go to `out/.build-local/times.log`.
- **`tools/ship-candidate.sh <kernel-dir> <branch> <candidate>`** goes from a
  kernel branch to a queued g0: it exports the patches, pushes, waits for CI,
  fetches that run's release and queues g0. Run it as the normal user (it calls
  sudo itself) after `gh auth login`, with no changes outside
  `candidates/<candidate>/`.

## Ladder

`docs/ladder.md` (see its Runbook for the commands per rung).

## Tests

    python3 -m unittest discover -s tests -v

## Credits

- yzddmr6, [linux-sm8750-erhai](https://github.com/yzddmr6/linux-sm8750-erhai)
- Akhil P Oommen and Jie Zhang (Qualcomm), the A830 series on dri-devel / linux-arm-msm:
  [lore.kernel.org/linux-arm-msm](https://lore.kernel.org/linux-arm-msm/)
- ROCKNIX, [ROCKNIX/distribution](https://github.com/ROCKNIX/distribution) (`bf8097a3fc`)
- TheMojoMan, [oneplus-erhai-linux](https://github.com/TheMojoMan/oneplus-erhai-linux)

## License

GPL-2.0-only.
