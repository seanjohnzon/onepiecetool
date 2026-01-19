#!/bin/bash
# Setup daily sync cron job for 6 AM EST (11 AM UTC)

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
SCRIPT="$PROJECT_DIR/daily_sync.py"
LOG_DIR="$PROJECT_DIR/logs"

# Create logs directory
mkdir -p "$LOG_DIR"

# Create the cron entry
CRON_ENTRY="0 11 * * * cd $PROJECT_DIR && $VENV_PYTHON $SCRIPT >> $LOG_DIR/cron.log 2>&1"

# Check if cron entry already exists
if crontab -l 2>/dev/null | grep -q "daily_sync.py"; then
    echo "⚠️  Cron job already exists. To update, run:"
    echo "   crontab -e"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
    echo "✅ Cron job added!"
    echo "   Schedule: Daily at 6 AM EST (11 AM UTC)"
    echo "   Script: $SCRIPT"
    echo "   Logs: $LOG_DIR/cron.log"
fi

echo ""
echo "Current crontab:"
crontab -l 2>/dev/null || echo "(empty)"
