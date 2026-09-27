#!/usr/bin/env bash
# The one entry point for a new machine. Clone this repository, then run:
#
#   ./bootstrap.sh            check each step and fix what it can
#   ./bootstrap.sh --check    check only; change nothing
#   ./bootstrap.sh --json     the report as JSON, for an agent
#
# It prints the commands for every step a person must do. Do them, then run
# it again until it says "Nothing left to do." scripts/bootstrap.py holds
# the steps, and bootstrap.settings.json holds every value particular to this
# workbench. A setting nobody has filled in leaves its step "skipped".
set -euo pipefail
cd "$(dirname "$0")"

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Xcode Command Line Tools are missing, and Python comes with them."
  echo "Run this, finish the installer, then run ./bootstrap.sh again:"
  echo "     xcode-select --install"
  exit 1
fi

exec /usr/bin/python3 scripts/bootstrap.py "$@"
