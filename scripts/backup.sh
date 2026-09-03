#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Vicenza Fitness Bot — Backup & Restore Utility
# ═══════════════════════════════════════════════════════════
#
# Usage:
#   ./backup.sh backup          — Crea backup con timestamp
#   ./backup.sh backup daily    — Crea backup giornaliero (sovrascrive)
#   ./backup.sh restore <file>  — Ripristina da backup
#   ./backup.sh list            — Lista backup disponibili
#   ./backup.sh cleanup         — Rimuovi backup più vecchi di 30 giorni
#
# ═══════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"
DATA_DIR="${PROJECT_DIR}/data"
DB_FILE="${PROJECT_DIR}/palestra.db"
ENV_FILE="${PROJECT_DIR}/.env"
FERNET_FILE="${PROJECT_DIR}/.fernet_key"
CONTAINER_NAME="vicenza-fitness-bot"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ═══════════════════════════════════════════════════════════
# BACKUP
# ═══════════════════════════════════════════════════════════

do_backup() {
    local mode="${1:-timestamp}"  # timestamp o daily
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    
    mkdir -p "$BACKUP_DIR"
    
    local filename
    if [ "$mode" = "daily" ]; then
        filename="bot_daily_$(date +%Y%m%d).tar.gz"
    else
        filename="bot_backup_${timestamp}.tar.gz"
    fi
    local filepath="${BACKUP_DIR}/${filename}"
    
    log_info "Creazione backup: ${filename}"
    
    # Stop bot temporarily for consistent backup
    local was_running=false
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        was_running=true
        log_info "Pausa bot per backup consistente..."
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    
    # Create tar.gz
    local files_to_backup=()
    [ -d "$DATA_DIR" ] && files_to_backup+=("data/")
    [ -f "$DB_FILE" ] && files_to_backup+=("palestra.db")
    [ -f "$ENV_FILE" ] && files_to_backup+=(".env")
    [ -f "$FERNET_FILE" ] && files_to_backup+=(".fernet_key")
    
    if [ ${#files_to_backup[@]} -eq 0 ]; then
        log_error "Nessun file da backuppare!"
        return 1
    fi
    
    tar czf "$filepath" -C "$PROJECT_DIR" "${files_to_backup[@]}"
    
    # Restart bot if it was running
    if [ "$was_running" = true ]; then
        log_info "Riavvio bot..."
        docker start "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    
    local size
    size=$(du -h "$filepath" | cut -f1)
    log_info "Backup creato: ${filepath} (${size})"
}

# ═══════════════════════════════════════════════════════════
# RESTORE
# ═══════════════════════════════════════════════════════════

do_restore() {
    local filepath="$1"
    
    if [ ! -f "$filepath" ]; then
        log_error "File non trovato: ${filepath}"
        return 1
    fi
    
    log_warn "⚠️  Restore da: $(basename "$filepath")"
    log_warn "Questo sovrascriverà i dati attuali!"
    read -p "Confermi? (s/N): " confirm
    if [ "$confirm" != "s" ] && [ "$confirm" != "S" ]; then
        log_info "Restore annullato."
        return 0
    fi
    
    # Stop bot
    log_info "Stop bot..."
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    
    # Backup attuale prima del restore
    log_info "Backup di sicurezza prima del restore..."
    do_backup "timestamp"
    
    # Extract
    log_info "Estrazione backup..."
    tar xzf "$filepath" -C "$PROJECT_DIR"
    
    # Fix permissions
    if [ -f "$FERNET_FILE" ]; then
        chmod 600 "$FERNET_FILE"
    fi
    
    # Restart bot
    log_info "Riavvio bot..."
    docker start "$CONTAINER_NAME" >/dev/null 2>&1 || true
    
    log_info "✅ Restore completato!"
}

# ═══════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════

do_list() {
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        log_warn "Nessun backup trovato in ${BACKUP_DIR}"
        return 0
    fi
    
    log_info "Backup disponibili in ${BACKUP_DIR}:"
    echo ""
    ls -lhS "$BACKUP_DIR"/*.tar.gz 2>/dev/null | awk '{print "  " $5 "  " $9}' | sed 's|.*/||'
    echo ""
    local count
    count=$(ls -1 "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l)
    local total
    total=$(du -sh "$BACKUP_DIR" | cut -f1)
    log_info "Totale: ${count} backup, ${total}"
}

# ═══════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════

do_cleanup() {
    local days="${1:-30}"
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_warn "Nessuna directory backup."
        return 0
    fi
    
    local count
    count=$(find "$BACKUP_DIR" -name "*.tar.gz" -mtime "+${days}" | wc -l)
    
    if [ "$count" -eq 0 ]; then
        log_info "Nessun backup più vecchio di ${days} giorni."
        return 0
    fi
    
    log_info "Rimozione ${count} backup più vecchi di ${days} giorni..."
    find "$BACKUP_DIR" -name "*.tar.gz" -mtime "+${days}" -delete
    log_info "✅ Cleanup completato."
}

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

case "${1:-help}" in
    backup)
        do_backup "${2:-timestamp}"
        ;;
    restore)
        if [ -z "${2:-}" ]; then
            log_error "Specifica il file di restore: ./backup.sh restore <file>"
            exit 1
        fi
        do_restore "$2"
        ;;
    list)
        do_list
        ;;
    cleanup)
        do_cleanup "${2:-30}"
        ;;
    help|*)
        echo "Vicenza Fitness Bot — Backup & Restore"
        echo ""
        echo "Usage:"
        echo "  $0 backup          Crea backup con timestamp"
        echo "  $0 backup daily    Crea backup giornaliero"
        echo "  $0 restore <file>  Ripristina da backup"
        echo "  $0 list            Lista backup disponibili"
        echo "  $0 cleanup [days]  Rimuovi backup più vecchi di N giorni (default: 30)"
        ;;
esac
