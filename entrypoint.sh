#!/bin/sh
# Started as root: the bind-mounted dirs (models/logs/recs) arrive owned by
# the host user, which the unprivileged stt user cannot write - the chown
# baked into the image cannot reach them. Fix ownership here, then drop
# privileges and run the command.
set -eu
# STT_UID / STT_GID run the server as the host user who owns the checkout, so models/, logs/ and
# recs/ stay writable to them without sudo. Unset, the image's own stt user (uid 1001) is used.
uid="${STT_UID:-$(id -u stt)}"
gid="${STT_GID:-$(id -g stt)}"
chown -R "$uid:$gid" /opt/models /opt/logs /opt/recs
# The inner `exec` matters: without it the shell stays PID 1 as the server's parent and does not
# forward SIGTERM, so every stop and redeploy waited out Docker's 10 s grace period and then
# SIGKILLed the server with requests still in flight.
exec setpriv --reuid "$uid" --regid "$gid" --clear-groups /bin/sh -c "exec $*"
