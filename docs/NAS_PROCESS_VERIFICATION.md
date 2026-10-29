# NAS verification after updating issue #590

Operator-run checks only. This PR does not access or change the live NAS.
Replace `<container>` with the actual Royal container name; do not paste secrets
or unredacted inspect output into public issues.

1. After the normal image update/recreation, check only the selected init fields:

   ```sh
   docker inspect --format 'init={{.HostConfig.Init}} entrypoint={{json .Config.Entrypoint}} pid={{.State.Pid}}' <container>
   docker top <container> -eo pid,ppid,stat,comm
   ```

   Expect Docker Init and/or the image's Tini as supervisor. Python should not
   be the unsupervised PID 1. A custom overridden entrypoint still needs init.
   Keep all current volume/secret mappings; no destructive migration is needed.

2. Record a baseline and repeat during normal operation, after queue completion,
   after cancelling a test download, after closing/reopening verification, and
   after a failed browser startup if one occurs naturally:

   ```sh
   docker exec <container> sh -c 'cat /sys/fs/cgroup/pids.current; cat /sys/fs/cgroup/pids.max'
   docker stats --no-stream <container>
   docker top <container> -eo ppid,stat,comm | awk 'NR>1 && $2 ~ /^Z/ {n++; kinds[$3]++} END {print "zombies", n+0; for (k in kinds) print k, kinds[k]}'
   ```

   On cgroup v1 hosts the relevant `pids.current` may instead be inside the
   pids controller's cgroup path. Use the actual container cgroup, not a host-wide
   total. `ps` lists names/status only; avoid `ps ... args` and full environment
   dumps, which can reveal credentials or stream URLs.

3. Compare the admin runtime diagnostic `owned_process_cleanup` before and after
   activity. After pools close, tracked open handles should return toward the
   baseline; cleanup errors should not grow. A reused active pool legitimately
   keeps its browser handle open. Concurrent downloads and ffprobe workers also
   legitimately change PID/thread counts; `pids.current` counts threads too.

4. Observe several queue/verification cycles and at least an overnight interval.
   Pass criteria: no accumulating Royal-parented Chromium/Crashpad zombies,
   stable post-idle PID/handle baseline, working extraction/verification, expected
   cancellation and unchanged Jellyfin batching/recognition. CPU snapshots alone
   cannot establish a process leak or a probe loop.

If accumulation remains, report timestamps, image revision, aggregate counts and
`pid,ppid,stat,comm` for the affected namespace, plus whether the init field or
entrypoint was overridden. Distinguish Royal-parented zombies from unrelated
host services. Never use global kill commands or delete media to investigate.
