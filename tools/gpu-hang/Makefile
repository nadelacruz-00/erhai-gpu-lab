# SPDX-License-Identifier: GPL-2.0-only
# Needs libegl-dev and libgles-dev (tablet/setup.sh installs them).
gpu-hang: gpu-hang.c
	$(CC) -O2 -Wall -o $@ $< -lEGL -lGLESv2 -lpthread

clean:
	rm -f gpu-hang

.PHONY: clean
