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
  `candidates/` from the pinned commit in `candidates/BASE_SHA`, with the
  tree's own `build-kernel.sh`, the candidate's patches and `extra.config`,
  and a `-lab-<candidate>` kernelrelease. Every requested config symbol is
  asserted in the final `.config`. The result is a Release: a UKI, a modules
  tarball, the `.config` and `SHA256SUMS`.
- **`erhai-gpu-lab`** (`tablet/erhai-lab`, stdlib-only python3; `sudo
  tablet/install.sh` installs it as `/usr/local/sbin/erhai-gpu-lab`) runs on the
  tablet. `erhai-gpu-lab fetch 60-gpu-reference` downloads a release, verifies every
  checksum and the UKI/modules version match, and installs the kernel beside
  the package kernel. rEFInd's default is never changed.

## Ladder

`docs/ladder.md`.

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
