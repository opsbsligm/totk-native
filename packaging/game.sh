#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$here"
exec "$here/ultratears" "$here/data/exefs"
