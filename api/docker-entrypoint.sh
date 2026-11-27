#!/bin/sh
# 서버는 일반 사용자(app)로 돌린다. Railway 볼륨은 root 소유로 마운트되므로, root로 시작해
# 데이터 폴더 소유권만 넘긴 뒤 권한을 내려 실행한다 (RAILWAY_RUN_UID=0로 계속 root로 도는 대신).
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R app:app "$DATA_DIR"
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
