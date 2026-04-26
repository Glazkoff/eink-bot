#!/usr/bin/env python3
"""Telegram bot for e-ink display — routes all display commands through MCP server API."""
import os
import json
import uuid
import aiohttp
import asyncio
from io import BytesIO
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# --- MCP Server API ---
MCP_BASE = os.getenv("MCP_API_URL", "http://localhost:8000")
WEB_BASE = os.getenv("MCP_WEB_URL", "http://localhost:5000")

# --- Image storage ---
IMAGE_DIR = Path("/home/orangepi/develop/eink_mcp/content/images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- Debug mode ---
debug_mode = True


async def api_get(url: str):
    """GET request to MCP Web API."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{WEB_BASE}{url}") as resp:
            return await resp.json()


async def api_post(url: str, data: dict):
    """POST request to MCP Web API."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{WEB_BASE}{url}", json=data) as resp:
            return await resp.json(), resp.status


async def api_delete(url: str):
    """DELETE request to MCP Web API."""
    async with aiohttp.ClientSession() as session:
        async with session.delete(f"{WEB_BASE}{url}") as resp:
            return await resp.json(), resp.status


async def mcp_alert(message: str, duration: int = 15):
    """Show alert via MCP (immediate interrupt)."""
    # Use the MCP tool endpoint (FastMCP HTTP transport)
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "show_alert",
                "arguments": {"message": message, "duration": duration}
            }
        }
        try:
            async with session.post(f"{MCP_BASE}/mcp/", json=payload) as resp:
                result = await resp.json()
                logger.info(f"MCP alert result: {result}")
                return True
        except Exception as e:
            logger.error(f"MCP alert failed: {e}")
            return False


async def add_text_to_plan(text: str, template: str = "clock_with_text", duration: int = 30, replan: bool = True):
    """Add text message to content plan via Web API."""
    data = {
        "type": template,
        "content": {"text": text},
        "duration": duration,
        "priority": 100 if replan else 0
    }
    result, status = await api_post("/api/plan", data)
    return result, status == 201


async def add_image_to_plan(image_path: str, template: str = "image_only", duration: int = 60, replan: bool = True):
    """Add image to content plan via Web API."""
    data = {
        "type": template,
        "content": {"image_path": image_path},
        "duration": duration,
        "priority": 100 if replan else 0
    }
    result, status = await api_post("/api/plan", data)
    return result, status == 201


async def get_status():
    """Get current display status."""
    return await api_get("/api/status")


async def get_plan():
    """Get upcoming content plan."""
    return await api_get("/api/plan")


# ===== Bot Handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message."""
    await update.message.reply_text(
        "🖥️ *E-Ink Display Bot*\n\n"
        "Commands:\n"
        "/text <message> — Display text\n"
        "/alert <message> — Show urgent alert\n"
        "/clock — Toggle clock mode\n"
        "/status — Display status\n"
        "/plan — Upcoming content\n"
        "/clear — Clear the queue\n"
        "/debug — Toggle debug mode\n\n"
        "📸 Send a photo to display it!",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def text_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /text — display text on e-ink via MCP."""
    if not context.args:
        await update.message.reply_text("Usage: /text <your message>")
        return

    text_message = " ".join(context.args)
    await update.message.reply_text("📝 Sending to display...")

    result, ok = await add_text_to_plan(text_message)
    if ok:
        await update.message.reply_text(f"✅ Text queued! {result.get('id', '')}")
    else:
        await update.message.reply_text(f"❌ Failed: {result.get('error', 'unknown')}")


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /alert — show immediate alert via MCP."""
    if not context.args:
        await update.message.reply_text("Usage: /alert <message>")
        return

    text_message = " ".join(context.args)
    await update.message.reply_text("🚨 Sending alert...")

    ok = await mcp_alert(text_message, duration=15)
    if ok:
        await update.message.reply_text("✅ Alert displayed!")
    else:
        await update.message.reply_text("❌ Failed to show alert")


async def clock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clock — toggle clock mode via MCP."""
    status = await get_status()
    if status.get("clock_mode"):
        # Clear the plan to let scheduler stay in clock mode (it already is)
        await update.message.reply_text("🕐 Clock mode is active. The display updates every minute.")
    else:
        # Clear all pending items so scheduler falls back to clock mode
        plan = await get_plan()
        if plan:
            for item in plan:
                await api_delete(f"/api/plan/{item['id']}")
        await update.message.reply_text("🕐 Cleared queue — clock mode should activate shortly.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current display status."""
    status = await get_status()
    lines = [f"📊 *Display Status*"]
    lines.append(f"Clock mode: {'✅' if status.get('clock_mode') else '❌'}")
    lines.append(f"Current: {status.get('current_item', 'idle')}")

    plan = await get_plan()
    lines.append(f"Queued items: {len(plan)}")
    if plan:
        for item in plan[:5]:
            lines.append(f"  • [{item.get('id')}] {item.get('screen_template_type')} ({item.get('duration')}s)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show upcoming content plan."""
    plan = await get_plan()
    if not plan:
        await update.message.reply_text("📭 Queue is empty — clock mode active")
        return

    lines = ["📋 *Upcoming content:*"]
    for item in plan[:10]:
        content = item.get('content', {})
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except:
                pass
        text = content.get('text', content.get('image_path', '?'))
        lines.append(f"  {item['id']}. {item['screen_template_type']}: {text[:40]} ({item['duration']}s)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the content queue."""
    plan = await get_plan()
    cleared = 0
    for item in plan:
        _, ok = await api_delete(f"/api/plan/{item['id']}")
        if ok:
            cleared += 1
    await update.message.reply_text(f"🗑️ Cleared {cleared} items from queue")


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle debug mode."""
    global debug_mode
    debug_mode = not debug_mode
    state = "ON 📸" if debug_mode else "OFF"
    await update.message.reply_text(f"🐛 Debug mode {state}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo — save and add to MCP plan."""
    await update.message.reply_text("📸 Processing photo...")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()

        # Save to MCP content images directory
        filename = f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        filepath = IMAGE_DIR / filename
        filepath.write_bytes(bytes(photo_bytes))

        logger.info(f"Photo saved to {filepath}")

        # Add to MCP plan
        result, ok = await add_image_to_plan(str(filepath), duration=120)
        if ok:
            await update.message.reply_text(f"✅ Photo queued for display!")

            if debug_mode:
                # Get current display image from MCP
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"{WEB_BASE}/api/display-image") as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                if img_data:
                                    await update.message.reply_photo(photo=BytesIO(img_data))
                except Exception as e:
                    logger.error(f"Debug image fetch failed: {e}")
        else:
            await update.message.reply_text(f"❌ Failed: {result.get('error', 'unknown')}")

    except Exception as e:
        logger.error(f"Photo processing failed: {e}")
        await update.message.reply_text(f"❌ Failed to process photo: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document images (sent as files)."""
    if not update.message.document.mime_type or not update.message.document.mime_type.startswith("image"):
        return

    await update.message.reply_text("📸 Processing image...")

    try:
        file = await context.bot.get_file(update.message.document.file_id)
        file_bytes = await file.download_as_bytearray()

        filename = f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        filepath = IMAGE_DIR / filename
        filepath.write_bytes(bytes(file_bytes))

        result, ok = await add_image_to_plan(str(filepath), duration=120)
        if ok:
            await update.message.reply_text("✅ Image queued!")
        else:
            await update.message.reply_text(f"❌ Failed: {result.get('error', 'unknown')}")

    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        await update.message.reply_text(f"❌ Failed: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception: {context.error}", exc_info=context.error)


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("text", text_command))
    application.add_handler(CommandHandler("alert", alert_command))
    application.add_handler(CommandHandler("clock", clock_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("plan", plan_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("debug", debug_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

    application.add_error_handler(error_handler)

    logger.info("Starting Telegram bot (MCP mode)...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
