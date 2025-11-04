#!/bin/bash

# A simple management script for a Telegram bot service on systemd

# --- Configuration ---
SERVICE_NAME="eink-bot.service"
TEMPLATE_FILE="./eink-bot.service.template"
SERVICE_FILE_PATH="/etc/systemd/system/$SERVICE_NAME"

# --- Colors for output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Helper Functions ---
print_status() {
    echo -e "${GREEN}--> $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}--> $1${NC}"
}

print_error() {
    echo -e "${RED}--> ERROR: $1${NC}"
}

# Check if the script is run as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root for this action. Please use sudo."
        exit 1
    fi
}

# --- Main Logic ---
case "$1" in
    setup)
        print_status "Starting bot service setup..."
        check_root

        if [ ! -f "$TEMPLATE_FILE" ]; then
            print_error "Template file not found at '$TEMPLATE_FILE'"
            exit 1
        fi

        print_status "Copying template to '$SERVICE_FILE_PATH'"
        cp "$TEMPLATE_FILE" "$SERVICE_FILE_PATH"

        print_status "Reloading systemd daemon..."
        systemctl daemon-reload

        print_status "Starting and enabling the service..."
        systemctl start "$SERVICE_NAME"
        systemctl enable "$SERVICE_NAME"

        echo ""
        print_status "Setup complete!"
        echo "You can check the status with: $0 status"
        ;;

    status)
        print_status "Showing service status for '$SERVICE_NAME'..."
        systemctl status "$SERVICE_NAME"
        ;;

    logs)
        print_status "Following live logs for '$SERVICE_NAME' (Press Ctrl+C to exit)..."
        journalctl -u "$SERVICE_NAME" -f
        ;;

    restart)
        print_status "Restarting service '$SERVICE_NAME'..."
        check_root
        systemctl restart "$SERVICE_NAME"
        print_status "Service restarted."
        ;;

    *)
        echo "Usage: $0 {setup|status|logs|restart}"
        echo ""
        echo "  setup   - Copies the template, reloads systemd, and starts/enables the service."
        echo "  status  - Shows the current status of the service."
        echo "  logs    - Shows the live logs of the service."
        echo "  restart - Restarts the service."
        exit 1
        ;;
esac

exit 0