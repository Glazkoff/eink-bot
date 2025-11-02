#!/bin/bash

# Telegram Bot for E-Ink Display
# This script starts the Telegram bot that receives images and displays them on the e-ink screen

# Activate virtual environment
source /home/orangepi/venv/bin/activate

# Change to the script directory
cd /home/orangepi/develop/eink_bot

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Error: .env file not found!"
    echo "Please create a .env file with your Telegram bot token:"
    echo "TELEGRAM_BOT_TOKEN=your_bot_token_here"
    exit 1
fi

# Check if python-telegram-bot is installed
if ! python -c "import telegram" 2>/dev/null; then
    echo "Installing python-telegram-bot..."
    pip install python-telegram-bot python-dotenv
fi

# Start the Telegram bot
echo "Starting Telegram bot for e-ink display..."
python telegram_bot.py