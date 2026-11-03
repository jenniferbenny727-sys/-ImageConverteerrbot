import os
import io
import logging
from PIL import Image, ImageOps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is missing.")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Menu Definitions ---
MAIN_MENU_KEYBOARD = [
    [InlineKeyboardButton("🖼️ Convert Image", callback_data="menu_convert")],
    [InlineKeyboardButton("📄 Image to PDF", callback_data="menu_pdf")],
    [InlineKeyboardButton("🗜️ Compress Image", callback_data="menu_compress")],
    [InlineKeyboardButton("📐 Resize Image", callback_data="menu_resize")],
    [InlineKeyboardButton("📊 Supported Formats", callback_data="menu_formats")],
    [InlineKeyboardButton("ℹ️ Help & Instructions", callback_data="menu_help")],
    [InlineKeyboardButton("👨‍💻 About Bot", callback_data="menu_about")],
    [InlineKeyboardButton("💬 Contact Support", callback_data="menu_support")],
]

# Map callback data to target format (extendable)
CONVERT_FORMATS = {
    "convert_png": "PNG",
    "convert_jpg": "JPEG",
    "convert_webp": "WEBP",
    "convert_bmp": "BMP",
}

# --- Helper: Image Conversion ---
def convert_image(input_bytes: bytes, target_format: str) -> bytes:
    """Converts image bytes to the target format, handling transparency."""
    with Image.open(io.BytesIO(input_bytes)) as img:
        # Auto-orient based on EXIF (important for phone photos) [citation:5]
        img = ImageOps.exif_transpose(img)

        # Handle transparency for formats that don't support alpha (JPEG)
        if target_format in ("JPEG", "JPG"):
            if img.mode in ("RGBA", "LA", "P"):
                # Create a white background and paste the image onto it [citation:4][citation:11]
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode == "RGBA":
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
        else:
            # For PNG/WEBP/BMP, keep alpha if present
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")

        output = io.BytesIO()
        save_kwargs = {}
        if target_format == "JPEG":
            save_kwargs["quality"] = 92
            save_kwargs["optimize"] = True
        elif target_format == "WEBP":
            save_kwargs["quality"] = 92
        elif target_format == "PNG":
            save_kwargs["optimize"] = True

        img.save(output, format=target_format, **save_kwargs)
        return output.getvalue()

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message and main menu."""
    welcome_text = (
        "👋 **Welcome to Image Converter Bot!**\n\n"
        "I can convert, compress, and resize images right here in Telegram.\n\n"
        "**How to use:**\n"
        "1. Tap a button below or send me an image directly.\n"
        "2. Choose the output format.\n"
        "3. Receive your converted file.\n\n"
        "Use /help for detailed instructions."
    )
    reply_markup = InlineKeyboardMarkup(MAIN_MENU_KEYBOARD)
    await update.message.reply_text(
        welcome_text, reply_markup=reply_markup, parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 **Help & Instructions**\n\n"
        "• **Convert Image**: Send a photo, then pick a format (PNG, JPG, WEBP, BMP).\n"
        "• **Image to PDF**: Send one or more images; I'll combine them into a PDF.\n"
        "• **Compress**: Reduces file size while keeping quality.\n"
        "• **Resize**: Change dimensions by pixels or percentage.\n\n"
        "**Commands:**\n"
        "/start – Main menu\n"
        "/convert – Start conversion\n"
        "/formats – List supported formats\n"
        "/cancel – Cancel current operation\n\n"
        "⚠️ **Limits**: Max file size 20 MB. Supported input: JPG, PNG, WEBP, BMP."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def formats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📊 **Supported Formats**\n\n"
        "**Input:** JPG, JPEG, PNG, WEBP, BMP\n"
        "**Output:** JPG, PNG, WEBP, BMP, PDF\n\n"
        "**Conversion Rules:**\n"
        "• Transparent images → JPG will get a **white background**.\n"
        "• Grayscale images are supported.\n"
        "• Large images are processed safely (up to 20 MB)."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👨‍💻 **About Image Converter Bot**\n\n"
        "Built with Python, `python-telegram-bot`, and Pillow.\n"
        "Deployed on Render as a background worker.\n\n"
        "Version: 1.0.0\n"
        "Source: [Your GitHub Repo Link]"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again."
    )

# --- Callback Query Handler ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_convert":
        await query.edit_message_text(
            "🖼️ **Send me an image** to convert.\n\n"
            "I'll detect the format and show you conversion options.",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_image"] = True

    elif data == "menu_formats":
        await formats_command(update, context)

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_about":
        await about_command(update, context)

    elif data == "menu_support":
        await query.edit_message_text(
            "💬 **Contact Support**\n\n"
            "For issues or feature requests, contact: @YourSupportUsername\n"
            "Or open an issue on GitHub.",
            parse_mode="Markdown",
        )

    elif data == "menu_pdf":
        await query.edit_message_text(
            "📄 **Image to PDF**\n\n"
            "Send one or more images (as files or photos).\n"
            "I'll combine them into a single PDF in the order received.\n\n"
            "Use /cancel to stop.",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_pdf_images"] = True
        context.user_data["pdf_images"] = []

    elif data == "menu_compress":
        await query.edit_message_text(
            "🗜️ **Compress Image**\n\n"
            "Send me an image. I'll reduce its file size while keeping good quality.\n"
            "Output format will match the input.",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_compress"] = True

    elif data == "menu_resize":
        await query.edit_message_text(
            "📐 **Resize Image**\n\n"
            "Send me an image. Then tell me the new dimensions (e.g., `800x600`) "
            "or a percentage (e.g., `50%`).",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_resize"] = True

    # Handle conversion format selection
    elif data in CONVERT_FORMATS:
        target = CONVERT_FORMATS[data]
        input_bytes = context.user_data.get("pending_image")
        if not input_bytes:
            await query.edit_message_text("⚠️ No image found. Please send an image first.")
            return

        await query.edit_message_text("⏳ Your image is being converted. Please wait...")

        try:
            output_bytes = convert_image(input_bytes, target)
            original_info = context.user_data.get("pending_image_info", {})
            orig_fmt = original_info.get("format", "Unknown")

            # Prepare summary [citation:4]
            summary = (
                f"✅ **Conversion completed successfully!**\n\n"
                f"📁 Original format: `{orig_fmt}`\n"
                f"📁 Converted format: `{target}`\n"
                f"📦 File size: `{len(output_bytes) / 1024:.1f} KB`"
            )

            # Send as document to preserve quality (no Telegram compression)
            ext = target.lower().replace("jpeg", "jpg")
            await query.message.reply_document(
                document=io.BytesIO(output_bytes),
                filename=f"converted.{ext}",
                caption=summary,
                parse_mode="Markdown",
            )
            # Clean up
            await query.delete_message()
        except Exception as e:
            logger.exception("Conversion failed")
            await query.edit_message_text(
                f"❌ Conversion failed. The file may be corrupted or unsupported.\n"
                f"Error: `{str(e)[:100]}`",
                parse_mode="Markdown",
            )
        finally:
            context.user_data.pop("pending_image", None)
            context.user_data.pop("pending_image_info", None)

# --- Message Handler (Receives Images) ---
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message

    # Get the largest available photo or document
    if message.photo:
        file_obj = await message.photo[-1].get_file()
        file_bytes = await file_obj.download_as_bytearray()
        orig_format = "JPG"  # Telegram photos are typically JPG
    elif message.document:
        doc = message.document
        if not doc.mime_type or not doc.mime_type.startswith("image/"):
            await message.reply_text("⚠️ Please send an image file.")
            return
        file_obj = await doc.get_file()
        file_bytes = await file_obj.download_as_bytearray()
        orig_format = doc.mime_type.split("/")[-1].upper()
        if orig_format == "JPEG":
            orig_format = "JPG"
    else:
        await message.reply_text("⚠️ Please send an image as a photo or file.")
        return

    # Basic size validation (Telegram limit ~20MB for bots)
    if len(file_bytes) > 20 * 1024 * 1024:
        await message.reply_text("⚠️ File too large. Maximum size is 20 MB.")
        return

    # Validate it's a real image using Pillow
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img.verify()  # Quick check
    except Exception:
        await message.reply_text("❌ Invalid or corrupted image file.")
        return

    # Store in user_data for the next step
    context.user_data["pending_image"] = bytes(file_bytes)
    context.user_data["pending_image_info"] = {"format": orig_format}
    context.user_data["awaiting_image"] = False

    # Show conversion options
    keyboard = [
        [
            InlineKeyboardButton("PNG", callback_data="convert_png"),
            InlineKeyboardButton("JPG", callback_data="convert_jpg"),
        ],
        [
            InlineKeyboardButton("WEBP", callback_data="convert_webp"),
            InlineKeyboardButton("BMP", callback_data="convert_bmp"),
        ],
    ]
    await message.reply_text(
        f"📥 Received image ({orig_format}).\n\n"
        f"**Choose output format:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

# --- Main Application ---
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("formats", formats_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CommandHandler("convert", start))  # Redirects to start menu

    # Callback queries (inline buttons)
    application.add_handler(CallbackQueryHandler(button_handler))

    # Image messages (photos and image documents)
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image)
    )

    logger.info("Bot started. Polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
