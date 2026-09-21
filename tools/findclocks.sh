#!/usr/bin/env bash
# Run in the server root (next to server.properties). Prints the world layout
# and every file that holds a dimension's game clock.
set -u
level=$(grep -E '^level-name=' server.properties 2>/dev/null | cut -d= -f2-)
level=${level:-world}
echo "level-name: $level"
echo

found=0
# Layout A: one folder per dimension, each with its own level.dat (older Paper/Spigot)
for d in "$level" "${level}_nether" "${level}_the_end"; do
    if [ -f "$d/level.dat" ]; then
        echo "  [A] $d/level.dat                 -> key Data.Time"
        found=1
    fi
done

# Layout B: one folder, dimensions inside, clock overridden per dimension (newer Paper)
for f in "$level"/dimensions/*/*/data/paper/level_overrides.dat; do
    if [ -f "$f" ]; then
        echo "  [B] $f  -> key data.game_time"
        found=1
    fi
done

echo
case $found in
0) echo "No clock files found - are you in the server root?";;
*) echo "A = per-world folders (edit Data.Time in each level.dat)"
   echo "B = single folder (edit data.game_time in each level_overrides.dat)"
   echo "Both listed? B is the one the server actually reads.";;
esac
