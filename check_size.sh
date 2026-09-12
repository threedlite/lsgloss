#!/bin/sh
# Fail if anything git would actually commit is near GitHub's file-size limits.
# GitHub hard-rejects files >100 MB and warns over 50 MB; we fail at 50 so a
# push is never refused after the fact.
#
# Note the file list: `git ls-files -co --exclude-standard` is tracked files
# plus untracked-but-not-ignored ones, which is exactly the set a `git add -A`
# would commit. Listing the working tree instead would flag models/ and
# data-sources/, which are ignored and never pushed.
limit=$((50 * 1024 * 1024))

git ls-files -co --exclude-standard > /tmp/.cs_list$$
oversize=$(while IFS= read -r f; do
    [ -f "$f" ] || continue
    size=$(wc -c < "$f")
    [ "$size" -gt "$limit" ] && printf 'TOO LARGE  %6s MB  %s\n' "$((size/1024/1024))" "$f"
done < /tmp/.cs_list$$)

total=$(while IFS= read -r f; do
    [ -f "$f" ] && wc -c < "$f"
done < /tmp/.cs_list$$ | awk '{s+=$1} END {print s+0}')
count=$(wc -l < /tmp/.cs_list$$ | tr -d ' ')
rm -f /tmp/.cs_list$$

printf 'committable tree: %s MB across %s files\n' "$((total/1024/1024))" "$count"
if [ -n "$oversize" ]; then
    printf '%s\n' "$oversize"
    echo "refusing: GitHub rejects files over 100 MB; keep every file under 50 MB."
    exit 1
fi
echo "OK: nothing over 50 MB."
