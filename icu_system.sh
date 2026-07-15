#!/bin/bash
# =============================================================================
# ICU — System Control Script
# Location: /opt/dev/icu/icu_system.sh
# Usage:
#   ./icu_system.sh stop      — graceful shutdown of all ICU services
#   ./icu_system.sh start     — start all ICU services
#   ./icu_system.sh restart   — stop then start
#   ./icu_system.sh status    — show status of all ICU services
# =============================================================================

set -euo pipefail

# --- ICU-owned services (stop/start managed by this script) ---
ICU_SERVICES=(
    "universe_sync_tv.service"
    "icu.service"
    "postgresql@18-main.service"
)

# --- Optional infrastructure (uncomment to include) ---
# INFRA_SERVICES=(
#     "cloudflared.service"
#     "nginx.service"
#     "docker.service"
# )

# --- Colours ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[ICU]${NC} $1"; }
warn() { echo -e "${YELLOW}[ICU]${NC} $1"; }
err()  { echo -e "${RED}[ICU]${NC} $1"; }

# -----------------------------------------------------------------------------
do_stop() {
    log "--- Stopping ICU services ---"
    # Stop in reverse dependency order
    for svc in "${ICU_SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc"; then
            log "Stopping $svc..."
            sudo systemctl stop "$svc"
            log "$svc stopped."
        else
            warn "$svc was not running — skipped."
        fi
    done
    log "--- All ICU services stopped ---"
}

# -----------------------------------------------------------------------------
do_start() {
    log "--- Starting ICU services ---"
    # Start in dependency order (reverse of stop)
    for svc in $(echo "${ICU_SERVICES[@]}" | tr ' ' '\n' | tac); do
        log "Starting $svc..."
        sudo systemctl start "$svc"
        # Brief pause to allow service to initialise before next starts
        sleep 2
        if systemctl is-active --quiet "$svc"; then
            log "$svc is running."
        else
            err "$svc failed to start — check: sudo systemctl status $svc"
            exit 1
        fi
    done
    log "--- All ICU services started ---"
}

# -----------------------------------------------------------------------------
do_status() {
    echo ""
    log "--- ICU Service Status ---"
    for svc in "${ICU_SERVICES[@]}"; do
        STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")
        if [ "$STATUS" = "active" ]; then
            echo -e "  ${GREEN}●${NC} $svc — $STATUS"
        else
            echo -e "  ${RED}●${NC} $svc — $STATUS"
        fi
    done
    echo ""
}

# -----------------------------------------------------------------------------
case "${1:-}" in
    stop)
        do_stop
        do_status
        ;;
    start)
        do_start
        do_status
        ;;
    restart)
        do_stop
        log "--- Waiting 3s before restart ---"
        sleep 3
        do_start
        do_status
        ;;
    status)
        do_status
        ;;
    *)
        err "Usage: $0 {stop|start|restart|status}"
        exit 1
        ;;
esac
