#!/bin/sh
exec python3 -c 'import sys; sys.path.insert(0, "/usr/share/pixelcommander"); from pixelcommander.app import main; main()' "$@"
