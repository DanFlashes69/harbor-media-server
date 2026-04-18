#!/bin/sh
set -e
export PATH=/usr/syno/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
mkdir -p /usr/local/bin /usr/local/lib/docker/cli-plugins /usr/bin
ln -sf /var/packages/ContainerManager/target/usr/bin/docker-compose /usr/local/bin/docker-compose
ln -sf /usr/local/bin/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
ln -sf /var/packages/ContainerManager/target/usr/bin/containerd /usr/bin/containerd
ln -sf /var/packages/ContainerManager/target/usr/bin/runc /usr/bin/runc
ln -sf /var/packages/ContainerManager/target/usr/bin/docker-init /usr/bin/docker-init
ln -sf /var/packages/ContainerManager/target/usr/bin/docker /usr/bin/docker
/var/packages/ContainerManager/scripts/start-stop-status stop || true
sleep 5
/var/packages/ContainerManager/scripts/start-stop-status start
sleep 10
docker version || true
docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}' || true
