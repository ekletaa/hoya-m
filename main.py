import os
import sqlite3
import random
import string
import tempfile
import shutil
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

# ========== الإعدادات ==========
TOKEN = "8670174584:AAEocVRBcLb3HJ44FfgzCl9LpDl4R3pddkg"
ADMIN_ID = 7890957907

DATA_DIR = "bot_data"
IMAGES_DIR = os.path.join(DATA_DIR, "images")
FONTS_DIR = os.path.join(DATA_DIR, "fonts")
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bot.db")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== حالات المحادثة ==========
WAIT_CODE = 0
USER_INPUT_TEXTS = 1

# إدارة الصور (إضافة صورة)
ADMIN_ADD_IMAGE_PHOTO = 10
ADMIN_ADD_IMAGE_NAME = 11

# إعدادات النصوص - الحالات
ADMIN_CONFIG_SELECT_IMAGE = 20
ADMIN_CONFIG_LIST_TEXTS = 21
ADMIN_CONFIG_EDIT_TEXT = 22
ADMIN_CONFIG_EDIT_PROMPT = 23
ADMIN_CONFIG_EDIT_INPUT_TYPE = 24
ADMIN_CONFIG_EDIT_FIXED_RANDOM = 25
ADMIN_CONFIG_EDIT_FIXED_TEXT = 26
ADMIN_CONFIG_EDIT_RANDOM_TEXTS = 27
ADMIN_CONFIG_EDIT_COORDS = 28
ADMIN_CONFIG_EDIT_FONT = 29
ADMIN_CONFIG_EDIT_FONT_SIZE = 30
ADMIN_CONFIG_EDIT_COLOR = 31
ADMIN_CONFIG_DELETE_TEXT = 32
ADMIN_CONFIG_ADD_NEW_TEXT = 33
ADMIN_CONFIG_NEW_TEXT_PROMPT = 34
ADMIN_CONFIG_NEW_TEXT_INPUT_TYPE = 35
ADMIN_CONFIG_NEW_TEXT_FIXED_RANDOM = 36
ADMIN_CONFIG_NEW_TEXT_FIXED = 37
ADMIN_CONFIG_NEW_TEXT_RANDOM = 38
ADMIN_CONFIG_NEW_TEXT_COORDS = 39
ADMIN_CONFIG_NEW_TEXT_FONT = 40
ADMIN_CONFIG_NEW_TEXT_FONT_SIZE = 41
ADMIN_CONFIG_NEW_TEXT_COLOR = 42

# ========== دوال مساعدة ==========
def get_iso_now():
    return datetime.now().isoformat()

def generate_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def save_font_file(document):
    file = await document.get_file()
    with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        new_path = os.path.join(FONTS_DIR, f"font_{datetime.now().timestamp()}.ttf")
        shutil.move(tmp.name, new_path)
        return new_path

def draw_text_on_image(image_path, text, config, output_path):
    img = Image.open(image_path).convert('RGB')
    draw = ImageDraw.Draw(img)
    x, y, w, h = config['x'], config['y'], config['width'], config['height']
    font_path = config['font_path']
    font_size = config.get('font_size', 30)
    color = tuple(map(int, config.get('text_color', '0,0,0').split(',')))
    reshaped = arabic_reshaper.reshape(text)
    bidi_text = get_display(reshaped)
    font = ImageFont.truetype(font_path, font_size)
    bbox = draw.textbbox((0, 0), bidi_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    while text_width > w - 10 and font_size > 10:
        font_size -= 1
        font = ImageFont.truetype(font_path, font_size)
        bbox = draw.textbbox((0, 0), bidi_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    text_x = x + (w - text_width) // 2
    text_y = y + (h - text_height) // 2
    draw.text((text_x, text_y), bidi_text, font=font, fill=color)
    img.save(output_path)

# ========== قاعدة البيانات ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, code TEXT, joined_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS codes (
        code TEXT PRIMARY KEY, used INTEGER DEFAULT 0, used_by INTEGER, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, file_path TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS text_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_id INTEGER, text_index INTEGER, prompt_text TEXT, is_user_input INTEGER DEFAULT 1,
        fixed_text TEXT, random_options TEXT,
        x INTEGER, y INTEGER, width INTEGER, height INTEGER,
        font_path TEXT, font_size INTEGER, text_color TEXT)''')
    conn.commit()
    conn.close()

init_db()

async def error_handler(update, context):
    logger.error(f"Error: {context.error}")
    if update and update.effective_chat:
        await context.bot.send_message(update.effective_chat.id, "⚠️ حدث خطأ. أعد /start")

# ========== لوحة الأدمن ==========
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    keyboard = [
        [InlineKeyboardButton("➕ إنشاء رمز اشتراك", callback_data="admin_gen_code")],
        [InlineKeyboardButton("👥 عدد المشتركين", callback_data="admin_list_users")],
        [InlineKeyboardButton("🖼️ إضافة صورة", callback_data="admin_add_image")],
        [InlineKeyboardButton("⚙️ إعدادات النصوص", callback_data="admin_configure_image")],
    ]
    reply = InlineKeyboardMarkup(keyboard)
    text = "🔧 *لوحة التحكم*"
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply, parse_mode='Markdown')
        except:
            pass
    else:
        await update.message.reply_text(text, reply_markup=reply, parse_mode='Markdown')

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_gen_code":
        code = generate_code()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO codes (code, created_at) VALUES (?,?)", (code, get_iso_now()))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ الرمز: `{code}`", parse_mode='Markdown')
        await asyncio.sleep(2)
        await admin_menu(update, context, edit=True)

    elif data == "admin_list_users":
        conn = sqlite3.connect(DB_PATH)
        try:
            users = conn.execute("SELECT user_id, username, full_name, code FROM users").fetchall()
        except Exception as e:
            logger.error(f"DB error: {e}")
            users = []
        conn.close()
        if not users:
            text = "لا يوجد مشتركين."
        else:
            lines = ["📋 *المشتركون:*"]
            for u in users:
                uid, uname, fname, code = u
                uname_display = f"@{uname}" if uname and uname.strip() else "لا يوجد"
                fname_display = fname if fname and fname.strip() else "لا يوجد"
                lines.append(f"🆔 `{uid}` - {uname_display} - {fname_display}\n🔑 `{code}`")
            text = "\n\n".join(lines)
        await query.edit_message_text(text, parse_mode='Markdown')
        await asyncio.sleep(4)
        await admin_menu(update, context, edit=True)

    elif data == "admin_add_image":
        await query.edit_message_text("📤 أرسل الصورة:")
        return ADMIN_ADD_IMAGE_PHOTO

    elif data == "admin_configure_image":
        context.user_data.clear()
        conn = sqlite3.connect(DB_PATH)
        images = conn.execute("SELECT id, name FROM images").fetchall()
        conn.close()
        if not images:
            await query.edit_message_text("⚠️ لا توجد صور.")
            await asyncio.sleep(2)
            await admin_menu(update, context, edit=True)
            return ConversationHandler.END
        keyboard = [[InlineKeyboardButton(name, callback_data=f"cfgimg_{id}")] for id, name in images]
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_menu")])
        await query.edit_message_text("اختر الصورة:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_CONFIG_SELECT_IMAGE

    elif data == "admin_menu":
        await admin_menu(update, context, edit=True)
        return ConversationHandler.END

# ========== إضافة صورة ==========
async def add_image_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("أرسل صورة فقط.")
        return ADMIN_ADD_IMAGE_PHOTO
    photo = update.message.photo[-1]
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        file = await photo.get_file()
        await file.download_to_drive(tmp.name)
        context.user_data['temp_path'] = tmp.name
    await update.message.reply_text("✅ أرسل اسم الصورة:")
    return ADMIN_ADD_IMAGE_NAME

async def add_image_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("الاسم مطلوب.")
        return ADMIN_ADD_IMAGE_NAME
    temp = context.user_data.get('temp_path')
    if not temp or not os.path.exists(temp):
        await update.message.reply_text("انتهت الجلسة.")
        return ConversationHandler.END
    safe_name = "".join(c for c in name if c.isalnum() or c in (' ','-','_')) or "image"
    new_path = os.path.join(IMAGES_DIR, f"{safe_name}_{int(datetime.now().timestamp())}.jpg")
    shutil.move(temp, new_path)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("INSERT INTO images (name, file_path, created_at) VALUES (?,?,?)",
                     (name, new_path, get_iso_now()))
        conn.commit()
        await update.message.reply_text(f"✅ تمت إضافة *{name}*", parse_mode='Markdown')
    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ الاسم موجود مسبقاً.")
        os.remove(new_path)
        return ADMIN_ADD_IMAGE_NAME
    finally:
        conn.close()
    await admin_menu(update, context)
    return ConversationHandler.END

# ========== إعدادات النصوص (القائمة الرئيسية) ==========
async def config_select_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("cfgimg_"):
        img_id = int(data.split("_")[1])
        context.user_data['config_img_id'] = img_id
        conn = sqlite3.connect(DB_PATH)
        texts = conn.execute("SELECT text_index, prompt_text FROM text_configs WHERE image_id=? ORDER BY text_index", (img_id,)).fetchall()
        conn.close()
        keyboard = []
        for idx, prompt in texts:
            keyboard.append([InlineKeyboardButton(f"📝 نص {idx}: {prompt[:20]}", callback_data=f"edit_text_{idx}")])
        keyboard.append([InlineKeyboardButton("➕ إضافة نص جديد", callback_data="add_new_text")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_configure_image")])
        await query.edit_message_text(f"إعدادات الصورة - اختر نصاً لتعديله:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_CONFIG_LIST_TEXTS

# ========== تعديل نص موجود ==========
async def config_list_texts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "add_new_text":
        conn = sqlite3.connect(DB_PATH)
        max_idx = conn.execute("SELECT COALESCE(MAX(text_index),0) FROM text_configs WHERE image_id=?", (context.user_data['config_img_id'],)).fetchone()[0]
        new_idx = max_idx + 1
        context.user_data['new_text_index'] = new_idx
        conn.close()
        await query.edit_message_text(f"📝 إضافة نص جديد (الرقم {new_idx})\nأرسل النص التوضيحي (مثل 'أرسل الاسم'):")
        return ADMIN_CONFIG_NEW_TEXT_PROMPT
    elif data.startswith("edit_text_"):
        idx = int(data.split("_")[2])
        context.user_data['edit_text_index'] = idx
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT prompt_text, is_user_input, fixed_text, random_options, x, y, width, height, font_path, font_size, text_color FROM text_configs WHERE image_id=? AND text_index=?", 
                           (context.user_data['config_img_id'], idx)).fetchone()
        conn.close()
        if not row:
            await query.edit_message_text("النص غير موجود.")
            return ADMIN_CONFIG_LIST_TEXTS
        context.user_data['edit_text_data'] = {
            'prompt': row[0],
            'is_user': row[1],
            'fixed': row[2],
            'random': row[3],
            'x': row[4], 'y': row[5], 'w': row[6], 'h': row[7],
            'font_path': row[8], 'font_size': row[9], 'color': row[10]
        }
        keyboard = [
            [InlineKeyboardButton("✏️ تعديل النص التوضيحي", callback_data="edit_prompt")],
            [InlineKeyboardButton("🔄 تعديل نوع الإدخال (مستخدم/تلقائي)", callback_data="edit_input_type")],
            [InlineKeyboardButton("📍 تعديل الإحداثيات", callback_data="edit_coords")],
            [InlineKeyboardButton("🖋️ تعديل الخط", callback_data="edit_font")],
            [InlineKeyboardButton("📏 تعديل حجم الخط", callback_data="edit_font_size")],
            [InlineKeyboardButton("🎨 تعديل اللون", callback_data="edit_color")],
            [InlineKeyboardButton("🗑️ حذف هذا النص", callback_data="delete_text")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_texts")]
        ]
        await query.edit_message_text(f"تعديل النص {idx}:\n{row[0]}\nاختر الخاصية:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_CONFIG_EDIT_TEXT

async def edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل النص التوضيحي الجديد:")
    return ADMIN_CONFIG_EDIT_PROMPT

async def edit_prompt_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_prompt = update.message.text
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE text_configs SET prompt_text=? WHERE image_id=? AND text_index=?", (new_prompt, img_id, idx))
    conn.commit()
    conn.close()
    context.user_data['edit_text_data']['prompt'] = new_prompt
    await update.message.reply_text("✅ تم تحديث النص التوضيحي.")
    await show_edit_menu(update, context)
    return ADMIN_CONFIG_EDIT_TEXT

async def edit_input_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("👤 يدخله المستخدم", callback_data="set_user")],
        [InlineKeyboardButton("🤖 تلقائي (ثابت/عشوائي)", callback_data="set_auto")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_edit")]
    ]
    await query.edit_message_text("اختر نوع النص:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_CONFIG_EDIT_INPUT_TYPE

async def set_input_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    is_user = 1 if choice == "set_user" else 0
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    if is_user == 0:
        context.user_data['changing_to_auto'] = True
        keyboard = [
            [InlineKeyboardButton("نص ثابت", callback_data="auto_fixed")],
            [InlineKeyboardButton("نصوص عشوائية", callback_data="auto_random")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_edit")]
        ]
        await query.edit_message_text("اختر نوع التلقائي:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_CONFIG_EDIT_FIXED_RANDOM
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE text_configs SET is_user_input=1, fixed_text=NULL, random_options=NULL WHERE image_id=? AND text_index=?", (img_id, idx))
        conn.commit()
        conn.close()
        context.user_data['edit_text_data']['is_user'] = 1
        await query.edit_message_text("✅ تم التحديث: النص سيطلب من المستخدم.")
        await show_edit_menu(update, context)
        return ADMIN_CONFIG_EDIT_TEXT

async def auto_fixed_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "auto_fixed":
        await query.edit_message_text("أرسل النص الثابت:")
        return ADMIN_CONFIG_EDIT_FIXED_TEXT
    else:
        await query.edit_message_text("أرسل النصوص العشوائية مفصولة بـ |||:")
        return ADMIN_CONFIG_EDIT_RANDOM_TEXTS

async def receive_fixed_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fixed = update.message.text
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE text_configs SET is_user_input=0, fixed_text=?, random_options=NULL WHERE image_id=? AND text_index=?", (fixed, img_id, idx))
    conn.commit()
    conn.close()
    context.user_data['edit_text_data']['is_user'] = 0
    context.user_data['edit_text_data']['fixed'] = fixed
    await update.message.reply_text("✅ تم تحديث النص الثابت.")
    await show_edit_menu(update, context)
    return ADMIN_CONFIG_EDIT_TEXT

async def receive_random_texts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    random_opts = update.message.text
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE text_configs SET is_user_input=0, fixed_text=NULL, random_options=? WHERE image_id=? AND text_index=?", (random_opts, img_id, idx))
    conn.commit()
    conn.close()
    context.user_data['edit_text_data']['is_user'] = 0
    context.user_data['edit_text_data']['random'] = random_opts
    await update.message.reply_text("✅ تم تحديث النصوص العشوائية.")
    await show_edit_menu(update, context)
    return ADMIN_CONFIG_EDIT_TEXT

async def edit_coords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل الإحداثيات الجديدة (x,y,width,height):\nمثال: 100,150,200,40")
    return ADMIN_CONFIG_EDIT_COORDS

async def receive_coords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.replace('،',',').split(',')
        x,y,w,h = map(int, parts[:4])
        idx = context.user_data['edit_text_index']
        img_id = context.user_data['config_img_id']
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE text_configs SET x=?, y=?, width=?, height=? WHERE image_id=? AND text_index=?", (x,y,w,h, img_id, idx))
        conn.commit()
        conn.close()
        context.user_data['edit_text_data'].update({'x':x,'y':y,'w':w,'h':h})
        await update.message.reply_text("✅ تم تحديث الإحداثيات.")
        await show_edit_menu(update, context)
        return ADMIN_CONFIG_EDIT_TEXT
    except:
        await update.message.reply_text("خطأ في الإحداثيات. أعد الإرسال.")
        return ADMIN_CONFIG_EDIT_COORDS

async def edit_font(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل ملف الخط الجديد (ttf):")
    return ADMIN_CONFIG_EDIT_FONT

async def receive_font(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("أرسل ملف ttf.")
        return ADMIN_CONFIG_EDIT_FONT
    font_path = await save_font_file(update.message.document)
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE text_configs SET font_path=? WHERE image_id=? AND text_index=?", (font_path, img_id, idx))
    conn.commit()
    conn.close()
    context.user_data['edit_text_data']['font_path'] = font_path
    await update.message.reply_text("✅ تم تحديث الخط.")
    await show_edit_menu(update, context)
    return ADMIN_CONFIG_EDIT_TEXT

async def edit_font_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل حجم الخط الجديد (رقم):")
    return ADMIN_CONFIG_EDIT_FONT_SIZE

async def receive_font_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        size = int(update.message.text)
        idx = context.user_data['edit_text_index']
        img_id = context.user_data['config_img_id']
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE text_configs SET font_size=? WHERE image_id=? AND text_index=?", (size, img_id, idx))
        conn.commit()
        conn.close()
        context.user_data['edit_text_data']['font_size'] = size
        await update.message.reply_text("✅ تم تحديث حجم الخط.")
        await show_edit_menu(update, context)
        return ADMIN_CONFIG_EDIT_TEXT
    except:
        await update.message.reply_text("أدخل رقماً صحيحاً.")
        return ADMIN_CONFIG_EDIT_FONT_SIZE

async def edit_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أرسل اللون الجديد (R,G,B):\nمثال: 0,0,0")
    return ADMIN_CONFIG_EDIT_COLOR

async def receive_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    color = update.message.text
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE text_configs SET text_color=? WHERE image_id=? AND text_index=?", (color, img_id, idx))
    conn.commit()
    conn.close()
    context.user_data['edit_text_data']['color'] = color
    await update.message.reply_text("✅ تم تحديث اللون.")
    await show_edit_menu(update, context)
    return ADMIN_CONFIG_EDIT_TEXT

async def delete_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = context.user_data['edit_text_index']
    img_id = context.user_data['config_img_id']
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM text_configs WHERE image_id=? AND text_index=?", (img_id, idx))
    conn.execute("UPDATE text_configs SET text_index = text_index - 1 WHERE image_id=? AND text_index > ?", (img_id, idx))
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ تم حذف النص.")
    await config_select_image(update, context)
    return ADMIN_CONFIG_LIST_TEXTS

async def back_to_texts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await config_select_image(update, context)
    return ADMIN_CONFIG_LIST_TEXTS

async def back_to_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_edit_menu(update, context)
    return ADMIN_CONFIG_EDIT_TEXT

async def show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data['edit_text_index']
    data = context.user_data.get('edit_text_data', {})
    prompt = data.get('prompt', '')
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل النص التوضيحي", callback_data="edit_prompt")],
        [InlineKeyboardButton("🔄 تعديل نوع الإدخال", callback_data="edit_input_type")],
        [InlineKeyboardButton("📍 تعديل الإحداثيات", callback_data="edit_coords")],
        [InlineKeyboardButton("🖋️ تعديل الخط", callback_data="edit_font")],
        [InlineKeyboardButton("📏 تعديل حجم الخط", callback_data="edit_font_size")],
        [InlineKeyboardButton("🎨 تعديل اللون", callback_data="edit_color")],
        [InlineKeyboardButton("🗑️ حذف هذا النص", callback_data="delete_text")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_texts")]
    ]
    text = f"تعديل النص {idx}:\n{prompt}\nاختر الخاصية:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== إضافة نص جديد ==========
async def new_text_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    context.user_data['new_text_prompt'] = prompt
    keyboard = [
        [InlineKeyboardButton("👤 يدخله المستخدم", callback_data="new_user")],
        [InlineKeyboardButton("🤖 تلقائي", callback_data="new_auto")]
    ]
    await update.message.reply_text("هل النص يدخله المستخدم أم تلقائي؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_CONFIG_NEW_TEXT_INPUT_TYPE

async def new_text_input_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    is_user = 1 if choice == "new_user" else 0
    context.user_data['new_text_is_user'] = is_user
    if is_user == 0:
        keyboard = [
            [InlineKeyboardButton("نص ثابت", callback_data="new_fixed")],
            [InlineKeyboardButton("نصوص عشوائية", callback_data="new_random")]
        ]
        await query.edit_message_text("اختر نوع التلقائي:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_CONFIG_NEW_TEXT_FIXED_RANDOM
    else:
        await query.edit_message_text("أرسل إحداثيات النص الجديد (x,y,width,height):")
        return ADMIN_CONFIG_NEW_TEXT_COORDS

async def new_text_fixed_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    context.user_data['new_text_is_random'] = (choice == "new_random")
    if choice == "new_fixed":
        await query.edit_message_text("أرسل النص الثابت:")
        return ADMIN_CONFIG_NEW_TEXT_FIXED
    else:
        await query.edit_message_text("أرسل النصوص العشوائية مفصولة بـ |||:")
        return ADMIN_CONFIG_NEW_TEXT_RANDOM

async def new_text_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data['new_text_fixed'] = text
    await update.message.reply_text("أرسل إحداثيات النص الجديد (x,y,width,height):")
    return ADMIN_CONFIG_NEW_TEXT_COORDS

async def new_text_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data['new_text_random'] = text
    await update.message.reply_text("أرسل إحداثيات النص الجديد (x,y,width,height):")
    return ADMIN_CONFIG_NEW_TEXT_COORDS

async def new_text_coords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.replace('،',',').split(',')
        x,y,w,h = map(int, parts[:4])
        context.user_data['new_text_coords'] = (x,y,w,h)
        await update.message.reply_text("أرسل ملف الخط (ttf):")
        return ADMIN_CONFIG_NEW_TEXT_FONT
    except:
        await update.message.reply_text("خطأ في الإحداثيات. أعد الإرسال.")
        return ADMIN_CONFIG_NEW_TEXT_COORDS

async def new_text_font(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("أرسل ملف ttf.")
        return ADMIN_CONFIG_NEW_TEXT_FONT
    font_path = await save_font_file(update.message.document)
    context.user_data['new_text_font'] = font_path
    await update.message.reply_text("أرسل حجم الخط:")
    return ADMIN_CONFIG_NEW_TEXT_FONT_SIZE

async def new_text_font_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        size = int(update.message.text)
        context.user_data['new_text_size'] = size
        await update.message.reply_text("أرسل اللون (R,G,B):")
        return ADMIN_CONFIG_NEW_TEXT_COLOR
    except:
        await update.message.reply_text("أدخل رقماً.")
        return ADMIN_CONFIG_NEW_TEXT_FONT_SIZE

async def new_text_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    color = update.message.text
    img_id = context.user_data['config_img_id']
    idx = context.user_data['new_text_index']
    prompt = context.user_data['new_text_prompt']
    is_user = context.user_data['new_text_is_user']
    coords = context.user_data['new_text_coords']
    font_path = context.user_data['new_text_font']
    font_size = context.user_data['new_text_size']
    fixed = context.user_data.get('new_text_fixed')
    random_opts = context.user_data.get('new_text_random')
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''INSERT INTO text_configs
        (image_id, text_index, prompt_text, is_user_input, fixed_text, random_options,
         x, y, width, height, font_path, font_size, text_color)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (img_id, idx, prompt, is_user, fixed, random_opts,
         coords[0], coords[1], coords[2], coords[3],
         font_path, font_size, color))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ تم إضافة النص الجديد.")
    await config_select_image(update, context)
    return ADMIN_CONFIG_LIST_TEXTS

# ========== المستخدم ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if user:
        return await show_main_menu(update, context)
    else:
        await update.message.reply_text("🔐 أرسل كود الاشتراك:")
        return WAIT_CODE

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT * FROM codes WHERE code=? AND used=0", (code,)).fetchone()
    if row:
        conn.execute("UPDATE codes SET used=1, used_by=? WHERE code=?", (user.id, code))
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?)", (user.id, user.username, user.full_name, code, get_iso_now()))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ تم الاشتراك!")
        return await show_main_menu(update, context)
    else:
        conn.close()
        await update.message.reply_text("❌ كود غير صالح.")
        return WAIT_CODE

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    images = conn.execute("SELECT id, name FROM images").fetchall()
    conn.close()
    if not images:
        await update.message.reply_text("لا توجد صور حالياً.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(name, callback_data=f"userimg_{id}")] for id, name in images]
    await update.message.reply_text("📸 اختر صورة:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def user_select_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("userimg_"):
        img_id = int(data.split("_")[1])
        context.user_data['sel_img'] = img_id
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT text_index, prompt_text, is_user_input FROM text_configs WHERE image_id=? ORDER BY text_index", (img_id,)).fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("الصورة غير مهيأة.")
            return ConversationHandler.END
        configs = {r[0]: {'prompt': r[1], 'is_user': r[2]} for r in rows}
        context.user_data['user_cfgs'] = configs
        context.user_data['user_texts'] = {}
        context.user_data['user_random_choices'] = {}
        first = next((idx for idx, cfg in configs.items() if cfg['is_user'] == 1), None)
        if first:
            context.user_data['user_cur'] = first
            await query.edit_message_text(f"✍️ {configs[first]['prompt']}")
            return USER_INPUT_TEXTS
        else:
            return await generate_and_send(update, context, query)
    elif data == "user_regenerate":
        img_id = context.user_data.get('sel_img')
        if not img_id:
            await query.answer("انتهت الجلسة.", show_alert=True)
            return ConversationHandler.END
        conn = sqlite3.connect(DB_PATH)
        has_random = conn.execute("SELECT 1 FROM text_configs WHERE image_id=? AND is_user_input=0 AND random_options IS NOT NULL AND random_options != ''", (img_id,)).fetchone()
        conn.close()
        if not has_random:
            await query.answer("⚠️ لا توجد نصوص عشوائية لتغييرها.", show_alert=True)
            return
        context.user_data['user_random_choices'] = {}
        await generate_and_send(update, context, query)
    elif data == "user_back_to_same":
        # إعادة طلب النصوص لنفس الصورة
        img_id = context.user_data.get('sel_img')
        if not img_id:
            await query.answer("انتهت الجلسة.", show_alert=True)
            return ConversationHandler.END
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT text_index, prompt_text, is_user_input FROM text_configs WHERE image_id=? ORDER BY text_index", (img_id,)).fetchall()
        conn.close()
        if not rows:
            await query.edit_message_text("الصورة غير مهيأة.")
            return ConversationHandler.END
        configs = {r[0]: {'prompt': r[1], 'is_user': r[2]} for r in rows}
        context.user_data['user_cfgs'] = configs
        context.user_data['user_texts'] = {}
        context.user_data['user_random_choices'] = {}
        first = next((idx for idx, cfg in configs.items() if cfg['is_user'] == 1), None)
        if first:
            context.user_data['user_cur'] = first
            await query.edit_message_text(f"✍️ {configs[first]['prompt']}")
            return USER_INPUT_TEXTS
        else:
            return await generate_and_send(update, context, query)

async def receive_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    idx = context.user_data.get('user_cur')
    if idx is None:
        await update.message.reply_text("انتهت الجلسة. أعد /start")
        return ConversationHandler.END
    context.user_data['user_texts'][idx] = text
    configs = context.user_data.get('user_cfgs', {})
    nxt = None
    for i in sorted(configs):
        if configs[i]['is_user'] and i not in context.user_data['user_texts']:
            nxt = i; break
    if nxt:
        context.user_data['user_cur'] = nxt
        await update.message.reply_text(f"✍️ {configs[nxt]['prompt']}")
        return USER_INPUT_TEXTS
    else:
        return await generate_and_send(update, context)

async def generate_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    img_id = context.user_data.get('sel_img')
    if not img_id:
        if query:
            await query.edit_message_text("انتهت الجلسة.")
        else:
            await update.message.reply_text("انتهت الجلسة.")
        return ConversationHandler.END
    user_texts = context.user_data.get('user_texts', {})
    conn = sqlite3.connect(DB_PATH)
    img_path = conn.execute("SELECT file_path FROM images WHERE id=?", (img_id,)).fetchone()
    if not img_path:
        conn.close()
        if query:
            await query.edit_message_text("الصورة غير موجودة.")
        else:
            await update.message.reply_text("الصورة غير موجودة.")
        return ConversationHandler.END
    img_path = img_path[0]
    rows = conn.execute("SELECT text_index, is_user_input, fixed_text, random_options, x,y,width,height, font_path, font_size, text_color FROM text_configs WHERE image_id=?", (img_id,)).fetchall()
    conn.close()
    final_texts = {}
    random_choices = context.user_data.get('user_random_choices', {})
    for r in rows:
        idx, is_user, fixed, rand, x,y,w,h, fpath, fsize, color = r
        if is_user:
            final_texts[idx] = user_texts.get(idx, "")
        else:
            if fixed:
                final_texts[idx] = fixed
            elif rand:
                opts = rand.split("|||")
                if idx in random_choices:
                    final_texts[idx] = random_choices[idx]
                else:
                    choice = random.choice(opts)
                    random_choices[idx] = choice
                    final_texts[idx] = choice
            else:
                final_texts[idx] = ""
    context.user_data['user_random_choices'] = random_choices
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        out = tmp.name
    try:
        shutil.copyfile(img_path, out)
        for idx, text in final_texts.items():
            if not text: continue
            conn = sqlite3.connect(DB_PATH)
            cfg = conn.execute("SELECT x,y,width,height,font_path,font_size,text_color FROM text_configs WHERE image_id=? AND text_index=?", (img_id, idx)).fetchone()
            conn.close()
            if cfg:
                config_dict = {'x':cfg[0],'y':cfg[1],'width':cfg[2],'height':cfg[3],'font_path':cfg[4],'font_size':cfg[5],'text_color':cfg[6]}
                draw_text_on_image(out, text, config_dict, out)
        keyboard = [
            [InlineKeyboardButton("🔄 تغيير العشوائي", callback_data="user_regenerate")],
            [InlineKeyboardButton("📝 اعداد قوميه اخرى..", callback_data="user_back_to_same")]
        ]
        caption = "✅ تم إنشاء الصورة"
        if query:
            with open(out, 'rb') as f:
                await query.edit_message_media(InputMediaPhoto(f, caption=caption), reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            with open(out, 'rb') as f:
                await update.message.reply_photo(f, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error generating image: {e}")
        if query:
            await query.edit_message_text("⚠️ فشل إنشاء الصورة.")
        else:
            await update.message.reply_text("⚠️ فشل إنشاء الصورة.")
    finally:
        if os.path.exists(out):
            os.unlink(out)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم الإلغاء.")
    await admin_menu(update, context)
    return ConversationHandler.END

# ========== تشغيل البوت ==========
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)

    # محادثة الاشتراك
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={WAIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code)]},
        fallbacks=[]
    ))

    # محادثة إضافة صورة
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_button_handler, pattern="^admin_add_image$")],
        states={
            ADMIN_ADD_IMAGE_PHOTO: [MessageHandler(filters.PHOTO, add_image_photo)],
            ADMIN_ADD_IMAGE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_image_name)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    ))

    # محادثة إعدادات النصوص (المعقدة)
    config_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_button_handler, pattern="^admin_configure_image$")],
        states={
            ADMIN_CONFIG_SELECT_IMAGE: [CallbackQueryHandler(config_select_image, pattern="^cfgimg_")],
            ADMIN_CONFIG_LIST_TEXTS: [CallbackQueryHandler(config_list_texts, pattern="^(edit_text_|add_new_text|back_to_texts)")],
            ADMIN_CONFIG_EDIT_TEXT: [CallbackQueryHandler(edit_prompt, pattern="^edit_prompt$"),
                                      CallbackQueryHandler(edit_input_type, pattern="^edit_input_type$"),
                                      CallbackQueryHandler(edit_coords, pattern="^edit_coords$"),
                                      CallbackQueryHandler(edit_font, pattern="^edit_font$"),
                                      CallbackQueryHandler(edit_font_size, pattern="^edit_font_size$"),
                                      CallbackQueryHandler(edit_color, pattern="^edit_color$"),
                                      CallbackQueryHandler(delete_text, pattern="^delete_text$"),
                                      CallbackQueryHandler(back_to_texts, pattern="^back_to_texts$"),
                                      CallbackQueryHandler(back_to_edit_menu, pattern="^back_to_edit$")],
            ADMIN_CONFIG_EDIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_prompt_receive)],
            ADMIN_CONFIG_EDIT_INPUT_TYPE: [CallbackQueryHandler(set_input_type, pattern="^(set_user|set_auto|back_to_edit)$")],
            ADMIN_CONFIG_EDIT_FIXED_RANDOM: [CallbackQueryHandler(auto_fixed_random, pattern="^(auto_fixed|auto_random|back_to_edit)$")],
            ADMIN_CONFIG_EDIT_FIXED_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_fixed_text)],
            ADMIN_CONFIG_EDIT_RANDOM_TEXTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_random_texts)],
            ADMIN_CONFIG_EDIT_COORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_coords)],
            ADMIN_CONFIG_EDIT_FONT: [MessageHandler(filters.Document.ALL, receive_font)],
            ADMIN_CONFIG_EDIT_FONT_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_font_size)],
            ADMIN_CONFIG_EDIT_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_color)],
            ADMIN_CONFIG_NEW_TEXT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_text_prompt)],
            ADMIN_CONFIG_NEW_TEXT_INPUT_TYPE: [CallbackQueryHandler(new_text_input_type, pattern="^(new_user|new_auto)$")],
            ADMIN_CONFIG_NEW_TEXT_FIXED_RANDOM: [CallbackQueryHandler(new_text_fixed_random, pattern="^(new_fixed|new_random)$")],
            ADMIN_CONFIG_NEW_TEXT_FIXED: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_text_fixed)],
            ADMIN_CONFIG_NEW_TEXT_RANDOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_text_random)],
            ADMIN_CONFIG_NEW_TEXT_COORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_text_coords)],
            ADMIN_CONFIG_NEW_TEXT_FONT: [MessageHandler(filters.Document.ALL, new_text_font)],
            ADMIN_CONFIG_NEW_TEXT_FONT_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_text_font_size)],
            ADMIN_CONFIG_NEW_TEXT_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_text_color)],
        },
        fallbacks=[CallbackQueryHandler(admin_button_handler, pattern="^admin_menu$"), CommandHandler("cancel", cancel)]
    )
    app.add_handler(config_conv)

    # محادثة المستخدم (جمع النصوص)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(user_select_image, pattern="^userimg_")],
        states={USER_INPUT_TEXTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_user_text)]},
        fallbacks=[CommandHandler("start", start)]
    ))

    # معالجات callback إضافية
    app.add_handler(CallbackQueryHandler(user_select_image, pattern="^(user_regenerate|user_back_to_same)$"))
    app.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^(admin_gen_code|admin_list_users|admin_menu)$"))

    # أمر /admin
    async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id == ADMIN_ID:
            await admin_menu(update, context)
        else:
            await update.message.reply_text("غير مصرح.")
    app.add_handler(CommandHandler("admin", admin_command))

    print("✅ البوت يعمل...")
    app.run_polling()

if __name__ == "__main__":
    main()