#!/bin/sh
# Persist pi's own credentials and defaults without moving its bundled extensions.
set -eu
pi_data_dir="${PILOT_DATA_DIR:-/workspace/data}"
mkdir -p "$pi_data_dir"
for name in auth settings; do
    target="$pi_data_dir/pi-$name.json"
    source="/root/.pi/agent/$name.json"
    if [ ! -e "$target" ]; then
        if [ -f "$source" ]; then
            cp "$source" "$target"
        else
            printf '{}\n' > "$target"
        fi
    fi
    chmod 600 "$target"
    ln -sfn "$target" "$source"
done
