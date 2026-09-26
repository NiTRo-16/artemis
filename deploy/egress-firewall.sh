#!/bin/sh
# Stop the Artemis container from reaching private or internal networks, whatever a scanned page tries.
#
# The app already refuses private addresses in code. This host firewall is the backstop for what code
# can't fully prevent (DNS rebinding: a domain that answers one lookup with a public address and the
# next with a private one). Run as root on the Docker host after `docker compose up`, and again after
# every reboot (see DEPLOY.md). Safe to re-run.
set -eu

SUBNET="${1:-172.30.0.0/24}"   # must match the egress network subnet in docker-compose.yml
CHAIN=ARTEMIS-EGRESS

iptables -N "$CHAIN" 2>/dev/null || iptables -F "$CHAIN"
for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 \
           192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4; do
    iptables -A "$CHAIN" -d "$net" -j DROP
done
iptables -A "$CHAIN" -j RETURN

# Docker leaves the DOCKER-USER chain for rules like this; it runs before Docker's own forwarding rules.
iptables -C DOCKER-USER -s "$SUBNET" -j "$CHAIN" 2>/dev/null || iptables -I DOCKER-USER -s "$SUBNET" -j "$CHAIN"

echo "Private-network egress blocked for $SUBNET."
