#!/usr/bin/env bash
# 2GB swapfile — mandatory on the 1GB VM before any Wine work.
set -euo pipefail
if swapon --show | grep -q '/swapfile'; then
  echo "swapfile already active"
else
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo "swapfile created + activated"
fi
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
sudo sysctl -w vm.swappiness=10 >/dev/null
free -m
