import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta, time
import jdatetime
import pytz
import json

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توکن ربات
TOKEN = "8211286788:AAEf0nacvSZy7uXfUmcxNDkGquujQuvYzbE"

# آیدی ادمین
ADMIN_ID = 6680287530

# تنظیمات دیتابیس
DB_CONFIG = {
    'dbname': 'exam_bot',
    'user': 'bot_user',
    'password': 'bot_password',
    'host': 'localhost',
    'port': '5432'
}

# منطقه زمانی تهران
TEHRAN_TZ = pytz.timezone('Asia/Tehran')

# تنظیمات پیجینیشن
QUESTIONS_PER_PAGE = 10

# وضعیت‌های مختلف آزمون
EXAM_STATUS = {
    'IN_PROGRESS': 'in_progress',
    'COMPLETED': 'completed',
    'WAITING_ANSWERS': 'waiting_answers',
    'CANCELLED': 'cancelled'
}

def get_db_connection():
    """ایجاد اتصال به دیتابیس"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def init_db():
    """ایجاد جداول دیتابیس"""
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("Failed to connect to database for initialization")
            return False
            
        cur = conn.cursor()
        
        # ایجاد جدول آزمون‌ها
        cur.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                course_name TEXT,
                topic_name TEXT,
                start_question INTEGER,
                end_question INTEGER,
                total_questions INTEGER,
                exam_duration INTEGER DEFAULT 0,
                elapsed_time REAL DEFAULT 0,
                answers TEXT,
                correct_answers TEXT,
                score REAL DEFAULT 0,
                wrong_questions TEXT,
                unanswered_questions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                jalali_date TEXT,
                tehran_time TEXT,
                question_pattern TEXT DEFAULT 'all',
                status TEXT DEFAULT 'completed',
                completed_at TIMESTAMP,
                exam_data TEXT
            )
        ''')
        
        # ایجاد جدول کاربران
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                jalali_date TEXT,
                tehran_time TEXT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ایجاد جدول برای ذخیره پاسخ‌های صحیح موقت
        cur.execute('''
            CREATE TABLE IF NOT EXISTS pending_exams (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                exam_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        
        # بررسی و اضافه کردن ستون‌های جدید اگر وجود ندارند
        columns_to_add = [
            ('status', 'TEXT DEFAULT \'completed\''),
            ('completed_at', 'TIMESTAMP'),
            ('exam_data', 'TEXT'),
            ('last_active', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        ]
        
        for column_name, column_type in columns_to_add:
            try:
                cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='users' AND column_name='{column_name}'
                """)
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
                    logger.info(f"Added missing column: {column_name}")
            except Exception as e:
                logger.error(f"Error checking/adding column {column_name}: {e}")
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False

def get_tehran_datetime():
    """دریافت تاریخ و زمان فعلی تهران"""
    tehran_now = datetime.now(TEHRAN_TZ)
    return tehran_now

def get_jalali_date():
    """دریافت تاریخ شمسی"""
    tehran_now = get_tehran_datetime()
    jalali_date = jdatetime.datetime.fromgregorian(datetime=tehran_now)
    return jalali_date.strftime('%Y/%m/%d')

def get_tehran_time():
    """دریافت زمان تهران"""
    tehran_now = get_tehran_datetime()
    return tehran_now.strftime('%H:%M:%S')

def calculate_questions_by_pattern(start_question, end_question, pattern):
    """محاسبه سوالات بر اساس الگوی انتخاب شده"""
    all_questions = list(range(start_question, end_question + 1))
    
    if pattern == 'all':
        return all_questions
    elif pattern == 'alternate':
        if start_question % 2 == 0:
            return [q for q in all_questions if q % 2 == 0]
        else:
            return [q for q in all_questions if q % 2 == 1]
    elif pattern == 'every_two':
        return [q for i, q in enumerate(all_questions, 1) if i % 3 == 1]
    elif pattern == 'every_three':
        return [q for i, q in enumerate(all_questions, 1) if i % 4 == 1]
    else:
        return all_questions

def get_pattern_name(pattern):
    """دریافت نام فارسی الگو"""
    pattern_names = {
        'all': 'همه سوالات (پشت سر هم)',
        'alternate': 'یکی در میان (زوج/فرد)',
        'every_two': 'دو تا در میان',
        'every_three': 'سه تا در میان'
    }
    return pattern_names.get(pattern, 'نامعلوم')

def get_exam_status_name(status):
    """دریافت نام فارسی وضعیت آزمون"""
    status_names = {
        'in_progress': 'در حال انجام',
        'completed': 'تکمیل شده',
        'waiting_answers': 'منتظر پاسخنامه',
        'cancelled': 'لغو شده'
    }
    return status_names.get(status, 'نامعلوم')

async def save_user_info(user):
    """ذخیره اطلاعات کاربر در دیتابیس"""
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            
            jalali_date = get_jalali_date()
            tehran_time = get_tehran_time()
            
            # ابتدا بررسی کنیم که آیا ستون last_active وجود دارد
            try:
                cur.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name, jalali_date, tehran_time, last_active)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_active = CURRENT_TIMESTAMP
                """, (
                    user.id,
                    user.username or '',
                    user.first_name or '',
                    user.last_name or '',
                    jalali_date,
                    tehran_time
                ))
            except Exception as column_error:
                # اگر ستون last_active وجود ندارد، بدون آن insert کنیم
                logger.warning(f"last_active column not found, inserting without it: {column_error}")
                cur.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name, jalali_date, tehran_time)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name
                """, (
                    user.id,
                    user.username or '',
                    user.first_name or '',
                    user.last_name or '',
                    jalali_date,
                    tehran_time
                ))
            
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        logger.error(f"Error saving user info: {e}")
    return False
async def notify_admin_new_user(context: ContextTypes.DEFAULT_TYPE, user):
    """ارسال اطلاعات کاربر جدید به ادمین"""
    try:
        jalali_date = get_jalali_date()
        tehran_time = get_tehran_time()
        
        user_info = f"""
🆕 کاربر جدید وارد ربات شد!

👤 نام: {user.first_name or ''} {user.last_name or ''}
🆔 یوزرنیم: @{user.username if user.username else 'ندارد'}
🔢 آیدی: {user.id}
📅 تاریخ: {jalali_date}
⏰ ساعت: {tehran_time}
"""
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=user_info
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")

def get_main_keyboard():
    """ایجاد کیبورد اصلی"""
    keyboard = [
        [KeyboardButton("📝 ساخت آزمون جدید"), KeyboardButton("📊 مشاهده نتایج")],
        [KeyboardButton("📚 راهنما"), KeyboardButton("ℹ️ درباره ربات")],
        [KeyboardButton("📋 آزمون‌های ناتمام")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    """ایجاد کیبورد لغو"""
    return ReplyKeyboardMarkup([[KeyboardButton("❌ لغو")]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور start"""
    user = update.effective_user
    
    is_new_user = await save_user_info(user)
    
    if is_new_user:
        await notify_admin_new_user(context, user)
    
    welcome_text = f"""
🎓 سلام {user.first_name} عزیز!

به ربات آزمون‌ساز هوشمند خوش آمدید! 🤖

✨ با این ربات می‌توانید:

📝 آزمون‌های تستی ایجاد کنید
⏱️ زمان‌بندی دقیق داشته باشید
📊 نتایج دقیق و تحلیلی دریافت کنید
📈 پیشرفت خود را پیگیری کنید
💾 آزمون‌ها را ذخیره و بعداً پاسخنامه وارد کنید

💡 برای شروع، از دکمه‌های زیر استفاده کنید:
"""
    
    keyboard = [
        [InlineKeyboardButton("🚀 شروع آزمون", callback_data="new_exam")],
        [InlineKeyboardButton("📊 نتایج من", callback_data="results")],
        [InlineKeyboardButton("📋 آزمون‌های ناتمام", callback_data="pending_exams")],
        [InlineKeyboardButton("📚 راهنمای استفاده", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )
    
    await update.message.reply_text(
        "از منوی زیر هم می‌توانید استفاده کنید:",
        reply_markup=get_main_keyboard()
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش راهنمای استفاده"""
    help_text = """
📚 راهنمای استفاده از ربات

🔹 ساخت آزمون:
1️⃣ نام درس را وارد کنید
2️⃣ نام مبحث را مشخص کنید
3️⃣ شماره اولین و آخرین سوال را بنویسید
4️⃣ الگوی سوالات را انتخاب کنید
5️⃣ مدت زمان آزمون را تعیین کنید (0 برای نامحدود)
6️⃣ به سوالات پاسخ دهید
7️⃣ انتخاب کنید: الآن پاسخنامه وارد کنید یا بعداً
8️⃣ نتیجه خود را مشاهده کنید

🔹 الگوهای سوالات:
• همه سوالات (پشت سر هم)
• یکی در میان (زوج/فرد)
• دو تا در میان
• سه تا در میان

🔹 ویژگی‌های جدید:
💾 ذخیره آزمون و تکمیل پاسخنامه بعداً
📋 مشاهده آزمون‌های ناتمام
⏰ تایمر زنده با نوار پیشرفت
📄 صفحه‌بندی سوالات (10 سوال در هر صفحه)
✅ امکان تغییر پاسخ‌ها
📊 محاسبه نمره با و بدون منفی
📈 ذخیره تاریخچه آزمون‌ها

💡 نکته مهم: هر 3 پاسخ اشتباه، معادل 1 پاسخ صحیح نمره منفی دارد.
"""
    
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text)
    else:
        await update.message.reply_text(help_text)

async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات درباره ربات"""
    about_text = """
ℹ️ درباره ربات آزمون‌ساز

🤖 نسخه: 3.0
👨‍💻 توسعه‌دهنده: تیم توسعه
📅 آخرین بروزرسانی: 1404

🌟 ویژگی‌های نسخه جدید:
• ذخیره آزمون و تکمیل پاسخنامه بعداً
• مدیریت آزمون‌های ناتمام
• رابط کاربری زیبا و حرفه‌ای
• کیبورد فارسی
• اعلان‌های ادمین
• گزارش‌گیری روزانه
• تایمر پیشرفته
• صفحه‌بندی هوشمند
• الگوهای متنوع سوالات

📧 برای پشتیبانی با ادمین در ارتباط باشید.
"""
    
    await update.message.reply_text(about_text)

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت callback query برای دکمه‌ها"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "new_exam":
        await new_exam(update, context)
    elif query.data == "results":
        await show_results(update, context)
    elif query.data == "pending_exams":
        await show_pending_exams(update, context)
    elif query.data == "help":
        await show_help(update, context)

async def handle_keyboard_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌های متنی از کیبورد"""
    text = update.message.text
    
    if text == "📝 ساخت آزمون جدید":
        await new_exam_from_message(update, context)
    elif text == "📊 مشاهده نتایج":
        await show_results(update, context)
    elif text == "📋 آزمون‌های ناتمام":
        await show_pending_exams(update, context)
    elif text == "📚 راهنما":
        await show_help(update, context)
    elif text == "ℹ️ درباره ربات":
        await show_about(update, context)
    else:
        await handle_message(update, context)

async def new_exam_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد آزمون جدید از طریق کیبورد"""
    user_id = update.effective_user.id
    context.user_data.pop('exam_setup', None)
    context.user_data['exam_setup'] = {'step': 'course_name'}
    
    await update.message.reply_text(
        "📚 لطفاً نام درس را وارد کنید:",
        reply_markup=get_cancel_keyboard()
    )

async def new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد آزمون جدید"""
    user_id = update.effective_user.id
    context.user_data.pop('exam_setup', None)
    context.user_data['exam_setup'] = {'step': 'course_name'}
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "📚 لطفاً نام درس را وارد کنید:",
            reply_markup=get_cancel_keyboard()
        )
    else:
        await update.message.reply_text(
            "📚 لطفاً نام درس را وارد کنید:",
            reply_markup=get_cancel_keyboard()
        )

def calculate_total_pages(total_questions):
    """محاسبه تعداد صفحات"""
    return (total_questions + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE

async def show_questions_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """نمایش سوالات به صورت صفحه‌بندی شده"""
    exam_setup = context.user_data['exam_setup']
    user_answers = exam_setup.get('answers', {})
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    total_questions = exam_setup.get('total_questions')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    question_list = exam_setup.get('question_list', [])
    
    total_pages = calculate_total_pages(total_questions)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * QUESTIONS_PER_PAGE
    end_idx = min(start_idx + QUESTIONS_PER_PAGE, total_questions)
    
    message_text = f"📚 درس: {course_name}\n"
    message_text += f"📖 مبحث: {topic_name}\n"
    message_text += f"📄 صفحه {page} از {total_pages}\n"
    message_text += f"🔢 الگو: {get_pattern_name(question_pattern)}\n\n"
    message_text += "📝 لطفاً به سوالات پاسخ دهید:\n\n"
    
    keyboard = []
    
    for i in range(start_idx, end_idx):
        question_num = question_list[i]
        current_answer = user_answers.get(str(question_num))
        question_buttons = []
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
            if current_answer == option:
                button_text = f"{option} ✅"
            else:
                button_text = str(option)
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    navigation_buttons = []
    if total_pages > 1:
        if page > 1:
            navigation_buttons.append(InlineKeyboardButton("◀️ صفحه قبلی", callback_data=f"page_{page-1}"))
        if page < total_pages:
            navigation_buttons.append(InlineKeyboardButton("صفحه بعدی ▶️", callback_data=f"page_{page+1}"))
        
        if navigation_buttons:
            keyboard.append(navigation_buttons)
    
    keyboard.append([InlineKeyboardButton("🎯 اتمام آزمون و ارسال پاسخ‌ها", callback_data="finish_exam")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    exam_setup['current_page'] = page
    context.user_data['exam_setup'] = exam_setup
    
    if 'exam_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=exam_setup['exam_message_id'],
                text=message_text,
                reply_markup=reply_markup
            )
            return
        except Exception as e:
            logger.error(f"Error editing message: {e}")
    
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        reply_markup=reply_markup
    )
    exam_setup['exam_message_id'] = message.message_id
    context.user_data['exam_setup'] = exam_setup

async def show_correct_answers_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """نمایش سوالات برای وارد کردن پاسخ‌های صحیح"""
    exam_setup = context.user_data['exam_setup']
    correct_answers = exam_setup.get('correct_answers', {})
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    total_questions = exam_setup.get('total_questions')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    question_list = exam_setup.get('question_list', [])
    
    total_pages = calculate_total_pages(total_questions)
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * QUESTIONS_PER_PAGE
    end_idx = min(start_idx + QUESTIONS_PER_PAGE, total_questions)
    
    answered_count = len(correct_answers)
    
    message_text = f"📚 درس: {course_name}\n"
    message_text += f"📖 مبحث: {topic_name}\n"
    message_text += f"📄 صفحه {page} از {total_pages}\n"
    message_text += f"🔢 الگو: {get_pattern_name(question_pattern)}\n"
    message_text += f"✅ پاسخ‌های وارد شده: {answered_count}/{total_questions}\n\n"
    message_text += "لطفاً پاسخ‌های صحیح را برای سوالات زیر انتخاب کنید:\n\n"
    
    keyboard = []
    
    for i in range(start_idx, end_idx):
        question_num = question_list[i]
        current_answer = correct_answers.get(str(question_num))
        question_buttons = []
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
            if current_answer == option:
                button_text = f"{option} ✅"
            else:
                button_text = str(option)
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"correct_ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    navigation_buttons = []
    if total_pages > 1:
        if page > 1:
            navigation_buttons.append(InlineKeyboardButton("◀️ صفحه قبلی", callback_data=f"correct_page_{page-1}"))
        if page < total_pages:
            navigation_buttons.append(InlineKeyboardButton("صفحه بعدی ▶️", callback_data=f"correct_page_{page+1}"))
        
        if navigation_buttons:
            keyboard.append(navigation_buttons)
    
    if answered_count == total_questions:
        keyboard.append([InlineKeyboardButton("✅ اتمام وارد کردن پاسخ‌های صحیح", callback_data="finish_correct_answers")])
    else:
        keyboard.append([InlineKeyboardButton("⏳ لطفاً برای همه سوالات پاسخ وارد کنید", callback_data="ignore")])
    
    keyboard.append([InlineKeyboardButton("🔢 وارد کردن پاسخ‌ها به صورت رشته عددی", callback_data="switch_to_text_input")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    exam_setup['correct_answers_page'] = page
    context.user_data['exam_setup'] = exam_setup
    
    if 'correct_answers_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=exam_setup['correct_answers_message_id'],
                text=message_text,
                reply_markup=reply_markup
            )
            return
        except Exception as e:
            logger.error(f"Error editing correct answers message: {e}")
    
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id
    else:
        chat_id = update.effective_chat.id
        
    message = await context.bot.send_message(
        chat_id=chat_id,
        text=message_text,
        reply_markup=reply_markup
    )
    exam_setup['correct_answers_message_id'] = message.message_id
    context.user_data['exam_setup'] = exam_setup

def create_progress_bar(percentage):
    """ایجاد نوار پیشرفت"""
    filled = min(10, int(percentage / 10))
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage:.1f}%"

async def show_pinned_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, exam_setup: dict):
    """تایمر با پیام پین شده"""
    exam_duration = exam_setup.get('exam_duration', 0)
    start_time = exam_setup.get('start_time')
    
    if not exam_duration or not start_time:
        return
    
    elapsed_time = (datetime.now() - start_time).total_seconds()
    remaining_time = max(0, exam_duration * 60 - elapsed_time)
    minutes = int(remaining_time // 60)
    seconds = int(remaining_time % 60)
    
    progress_percent = (elapsed_time / (exam_duration * 60)) * 100
    progress_bar = create_progress_bar(progress_percent)
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    timer_text = f"📚 {course_name} - {topic_name}\n🔢 {get_pattern_name(question_pattern)}\n⏳ باقیمانده: {minutes:02d}:{seconds:02d}\n{progress_bar}"
    
    if 'timer_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=exam_setup['timer_message_id'],
                text=timer_text,
                parse_mode='Markdown'
            )
            try:
                await context.bot.pin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id'],
                    disable_notification=True
                )
            except:
                pass
        except Exception as e:
            logger.error(f"Error editing timer message: {e}")
    else:
        try:
            message = await context.bot.send_message(
                chat_id=user_id,
                text=timer_text,
                parse_mode='Markdown'
            )
            exam_setup['timer_message_id'] = message.message_id
            try:
                await context.bot.pin_chat_message(
                    chat_id=user_id,
                    message_id=message.message_id,
                    disable_notification=True
                )
            except:
                pass
            if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
                context.bot_data['user_exams'][user_id] = exam_setup
        except Exception as e:
            logger.error(f"Error sending timer message: {e}")

async def update_timer(context: ContextTypes.DEFAULT_TYPE):
    """تایمر برای به روزرسانی زمان"""
    job = context.job
    user_id = job.chat_id
    
    if 'user_exams' not in context.bot_data:
        return
    
    if user_id not in context.bot_data['user_exams']:
        return
    
    exam_setup = context.bot_data['user_exams'][user_id]
    
    if exam_setup.get('step') != 4:
        return
    
    exam_duration = exam_setup.get('exam_duration', 0)
    start_time = exam_setup.get('start_time')
    
    if not exam_duration or not start_time:
        return
    
    elapsed_time = (datetime.now() - start_time).total_seconds()
    remaining_time = max(0, exam_duration * 60 - elapsed_time)
    
    if remaining_time <= 0:
        await finish_exam_auto(context, user_id)
        return
    
    await show_pinned_timer(context, user_id, exam_setup)

async def finish_exam_auto(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """اتمام خودکار آزمون وقتی زمان تمام شد"""
    if 'user_exams' not in context.bot_data or user_id not in context.bot_data['user_exams']:
        return
    
    exam_setup = context.bot_data['user_exams'][user_id]
    
    exam_setup['step'] = 'waiting_for_correct_answers_inline'
    exam_setup['correct_answers'] = {}
    context.bot_data['user_exams'][user_id] = exam_setup
    
    start_time = exam_setup.get('start_time')
    elapsed_time = calculate_elapsed_time(start_time)
    exam_setup['elapsed_time'] = elapsed_time
    
    job_name = f"timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    
    total_questions = exam_setup.get('total_questions')
    answered_count = len(exam_setup.get('answers', {}))
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    try:
        message = await context.bot.send_message(
            chat_id=user_id,
            text=f"📚 {course_name} - {topic_name}\n"
                 f"🔢 {get_pattern_name(question_pattern)}\n"
                 f"⏰ زمان آزمون به پایان رسید!\n"
                 f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
                 f"لطفاً پاسخ‌های صحیح را با استفاده از دکمه‌های زیر وارد کنید:"
        )
        
        await show_correct_answers_page(context, context, page=1)
        
        if 'timer_message_id' in exam_setup:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id']
                )
            except:
                pass
            
    except Exception as e:
        logger.error(f"Error sending auto-finish message: {e}")

def calculate_elapsed_time(start_time):
    """محاسبه زمان سپری شده از شروع آزمون"""
    if not start_time:
        return 0
    elapsed = datetime.now() - start_time
    return round(elapsed.total_seconds() / 60, 2)

async def save_pending_exam(user_id: int, exam_setup: dict):
    """ذخیره آزمون در حالت انتظار برای تکمیل بعدی"""
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            
            # ذخیره داده‌های آزمون
            exam_data = {
                'course_name': exam_setup.get('course_name'),
                'topic_name': exam_setup.get('topic_name'),
                'start_question': exam_setup.get('start_question'),
                'end_question': exam_setup.get('end_question'),
                'total_questions': exam_setup.get('total_questions'),
                'exam_duration': exam_setup.get('exam_duration'),
                'elapsed_time': exam_setup.get('elapsed_time'),
                'answers': exam_setup.get('answers', {}),
                'question_pattern': exam_setup.get('question_pattern', 'all'),
                'question_list': exam_setup.get('question_list', []),
                'start_time': exam_setup.get('start_time').isoformat() if exam_setup.get('start_time') else None
            }
            
            jalali_date = get_jalali_date()
            tehran_time = get_tehran_time()
            
            cur.execute(
                """
                INSERT INTO exams 
                (user_id, course_name, topic_name, start_question, end_question, total_questions, 
                 exam_duration, elapsed_time, answers, status, jalali_date, tehran_time, question_pattern, exam_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    exam_setup.get('course_name'),
                    exam_setup.get('topic_name'),
                    exam_setup.get('start_question'),
                    exam_setup.get('end_question'),
                    exam_setup.get('total_questions'),
                    exam_setup.get('exam_duration'),
                    exam_setup.get('elapsed_time'),
                    str(exam_setup.get('answers', {})),
                    EXAM_STATUS['WAITING_ANSWERS'],
                    jalali_date,
                    tehran_time,
                    exam_setup.get('question_pattern', 'all'),
                    json.dumps(exam_data)
                )
            )
            
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        logger.error(f"Error saving pending exam: {e}")
    return False

async def show_completion_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش گزینه‌های تکمیل آزمون"""
    exam_setup = context.user_data['exam_setup']
    
    total_questions = exam_setup.get('total_questions')
    answered_count = len(exam_setup.get('answers', {}))
    elapsed_time = exam_setup.get('elapsed_time', 0)
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    summary_text = f"""
📋 خلاصه آزمون:

📚 درس: {course_name}
📖 مبحث: {topic_name}
🔢 الگو: {get_pattern_name(question_pattern)}
📝 تعداد سوالات: {total_questions}
✅ پاسخ‌های داده شده: {answered_count}
⏰ زمان صرف شده: {elapsed_time:.2f} دقیقه

💡 اکنون چه کاری می‌خواهید انجام دهید؟
"""
    
    keyboard = [
        [InlineKeyboardButton("✅ الآن پاسخنامه وارد کن", callback_data="enter_answers_now")],
        [InlineKeyboardButton("💾 ذخیره برای بعد", callback_data="save_for_later")],
        [InlineKeyboardButton("🔙 بازگشت به آزمون", callback_data="back_to_exam")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=summary_text,
                reply_markup=reply_markup
            )
        except Exception as e:
            # اگر ویرایش پیام ممکن نبود، پیام جدید ارسال کن
            logger.error(f"Error editing message: {e}")
            await update.callback_query.message.reply_text(
                text=summary_text,
                reply_markup=reply_markup
            )
    else:
        await update.message.reply_text(
            text=summary_text,
            reply_markup=reply_markup
    )

async def handle_completion_choice(update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str):
    """مدیریت انتخاب کاربر برای تکمیل آزمون"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    exam_setup = context.user_data.get('exam_setup', {})
    
    if choice == "enter_answers_now":
        # ادامه با وارد کردن پاسخ‌های صحیح
        exam_setup['step'] = 'waiting_for_correct_answers_inline'
        exam_setup['correct_answers'] = {}
        context.user_data['exam_setup'] = exam_setup
        
        # ارسال پیام جدید به جای ویرایش پیام قبلی
        await query.message.reply_text(
            text="لطفاً پاسخ‌های صحیح را با استفاده از دکمه‌های زیر وارد کنید:"
        )
        await show_correct_answers_page(update, context, page=1)
        
    elif choice == "save_for_later":
        # ذخیره آزمون برای تکمیل بعدی
        success = await save_pending_exam(user_id, exam_setup)
        
        if success:
            # پاک کردن وضعیت آزمون و تایمر
            context.user_data.pop('exam_setup', None)
            if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
                # آنپین کردن پیام تایمر
                exam_setup = context.bot_data['user_exams'][user_id]
                if 'timer_message_id' in exam_setup:
                    try:
                        await context.bot.unpin_chat_message(
                            chat_id=user_id,
                            message_id=exam_setup['timer_message_id']
                        )
                    except:
                        pass
                context.bot_data['user_exams'].pop(user_id, None)
            
            # حذف تایمر
            job_name = f"timer_{user_id}"
            current_jobs = context.job_queue.get_jobs_by_name(job_name)
            for job in current_jobs:
                job.schedule_removal()
            
            # ارسال پیام جدید
            await query.message.reply_text(
                text="✅ آزمون شما با موفقیت ذخیره شد.\n\n"
                     "📋 می‌توانید از طریق منوی 'آزمون‌های ناتمام' در آینده پاسخنامه را وارد کرده و نتایج نهایی را مشاهده کنید.",
                reply_markup=get_main_keyboard()
            )
        else:
            await query.message.reply_text(
                text="❌ خطایی در ذخیره‌سازی آزمون رخ داد. لطفاً مجدداً تلاش کنید."
            )
    
    elif choice == "back_to_exam":
        # بازگشت به صفحه سوالات
        current_page = exam_setup.get('current_page', 1)
        await show_questions_page(update, context, current_page)


async def show_pending_exams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش آزمون‌های ناتمام کاربر"""
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            if update.callback_query:
                await update.callback_query.message.reply_text("⚠️ در حال حاضر امکان دسترسی به آزمون‌های ناتمام وجود ندارد.")
            else:
                await update.message.reply_text("⚠️ در حال حاضر امکان دسترسی به آزمون‌های ناتمام وجود ندارد.")
            return
            
        cur = conn.cursor()
        
        cur.execute(
            """SELECT id, course_name, topic_name, created_at, start_question, end_question, 
                      total_questions, exam_duration, elapsed_time, question_pattern, jalali_date, tehran_time 
               FROM exams 
               WHERE user_id = %s AND status = %s 
               ORDER BY created_at DESC""",
            (user_id, EXAM_STATUS['WAITING_ANSWERS'])
        )
        
        pending_exams = cur.fetchall()
        cur.close()
        conn.close()
        
        if pending_exams:
            if len(pending_exams) == 1:
                # اگر فقط یک آزمون ناتمام وجود دارد، مستقیماً نمایش داده می‌شود
                exam_id = pending_exams[0][0]
                await load_pending_exam(update, context, exam_id)
            else:
                # نمایش لیست آزمون‌های ناتمام
                message_text = "📋 آزمون‌های ناتمام شما:\n\n"
                keyboard = []
                
                for i, exam in enumerate(pending_exams, 1):
                    exam_id, course_name, topic_name, created_at, start_q, end_q, total_questions, duration, elapsed, pattern, jalali_date, tehran_time = exam
                    
                    message_text += f"{i}. {course_name} - {topic_name}\n"
                    message_text += f"   سوالات {start_q}-{end_q} - الگو: {get_pattern_name(pattern)}\n"
                    message_text += f"   تاریخ: {jalali_date} {tehran_time}\n\n"
                    
                    keyboard.append([InlineKeyboardButton(
                        f"{i}. {course_name} - {topic_name}", 
                        callback_data=f"load_exam_{exam_id}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    await update.callback_query.message.reply_text(
                        message_text,
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_text(
                        message_text,
                        reply_markup=reply_markup
                    )
        else:
            message_text = "🎉 هیچ آزمون ناتمامی ندارید!"
            
            if update.callback_query:
                await update.callback_query.message.reply_text(message_text)
            else:
                await update.message.reply_text(message_text)
                
    except Exception as e:
        logger.error(f"Error retrieving pending exams: {e}")
        message_text = "⚠️ خطایی در دریافت آزمون‌های ناتمام رخ داد."
        
        if update.callback_query:
            await update.callback_query.message.reply_text(message_text)
        else:
            await update.message.reply_text(message_text)

async def load_pending_exam(update: Update, context: ContextTypes.DEFAULT_TYPE, exam_id: int):
    """بارگذاری آزمون ناتمام برای تکمیل"""
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            await update.callback_query.message.reply_text("⚠️ خطا در اتصال به دیتابیس.")
            return
            
        cur = conn.cursor()
        
        cur.execute(
            """SELECT course_name, topic_name, start_question, end_question, total_questions,
                      exam_duration, elapsed_time, answers, question_pattern, exam_data
               FROM exams WHERE id = %s AND user_id = %s AND status = %s""",
            (exam_id, user_id, EXAM_STATUS['WAITING_ANSWERS'])
        )
        
        exam = cur.fetchone()
        cur.close()
        conn.close()
        
        if exam:
            course_name, topic_name, start_q, end_q, total_questions, duration, elapsed, answers_str, pattern, exam_data_str = exam
            
            # بازیابی داده‌های آزمون
            exam_setup = {
                'course_name': course_name,
                'topic_name': topic_name,
                'start_question': start_q,
                'end_question': end_q,
                'total_questions': total_questions,
                'exam_duration': duration,
                'elapsed_time': elapsed,
                'question_pattern': pattern,
                'step': 'waiting_for_correct_answers_inline',
                'correct_answers': {},
                'exam_id': exam_id,
                'answers': {}
            }
            
            # بازیابی پاسخ‌های کاربر
            try:
                if answers_str and answers_str != '{}':
                    answers = eval(answers_str) if answers_str else {}
                    exam_setup['answers'] = answers
                else:
                    exam_setup['answers'] = {}
            except:
                exam_setup['answers'] = {}
            
            # بازیابی لیست سوالات
            if exam_data_str:
                try:
                    exam_data = json.loads(exam_data_str)
                    exam_setup['question_list'] = exam_data.get('question_list', [])
                except:
                    exam_setup['question_list'] = calculate_questions_by_pattern(start_q, end_q, pattern)
            else:
                exam_setup['question_list'] = calculate_questions_by_pattern(start_q, end_q, pattern)
            
            # *** این خط کلیدی است - ذخیره exam_setup در context.user_data ***
            context.user_data['exam_setup'] = exam_setup
            
            await update.callback_query.message.reply_text(
                f"📚 بارگذاری آزمون: {course_name} - {topic_name}\n"
                f"🔢 الگو: {get_pattern_name(pattern)}\n"
                f"📝 لطفاً پاسخ‌های صحیح را وارد کنید:"
            )
            
            await show_correct_answers_page(update, context, page=1)
            
        else:
            await update.callback_query.message.reply_text("❌ آزمون مورد نظر یافت نشد.")
            
    except Exception as e:
        logger.error(f"Error loading pending exam: {e}")
        await update.callback_query.message.reply_text("⚠️ خطایی در بارگذاری آزمون رخ داد.")

async def update_exam_with_correct_answers(context: ContextTypes.DEFAULT_TYPE, user_id: int, exam_setup: dict, correct_answers_str: str):
    """به روزرسانی آزمون با پاسخ‌های صحیح و محاسبه نتایج"""
    try:
        conn = get_db_connection()
        if conn is None:
            return False
            
        cur = conn.cursor()
        
        user_answers = exam_setup.get('answers', {})
        correct_answers = exam_setup.get('correct_answers', {})
        question_list = exam_setup.get('question_list', [])
        
        correct_questions = []
        wrong_questions = []
        unanswered_questions = []
        
        for question_num in question_list:
            str_question_num = str(question_num)
            correct_answer = correct_answers.get(str_question_num)
            user_answer = user_answers.get(str_question_num)
            
            if user_answer is None:
                unanswered_questions.append(question_num)
            elif user_answer == correct_answer:
                correct_questions.append(question_num)
            else:
                wrong_questions.append(question_num)
        
        # محاسبه نتایج
        correct_count = len(correct_questions)
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)
        total_questions = len(question_list)

        # محاسبه نمره منفی
        raw_score = correct_count
        penalty = wrong_count / 3.0
        final_score = max(0, raw_score - penalty)
        final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0
        
        # به روزرسانی رکورد آزمون
        cur.execute(
            """
            UPDATE exams 
            SET correct_answers = %s, score = %s, wrong_questions = %s, 
                unanswered_questions = %s, status = %s, completed_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            """,
            (
                correct_answers_str,
                final_percentage,
                str(wrong_questions),
                str(unanswered_questions),
                EXAM_STATUS['COMPLETED'],
                exam_setup.get('exam_id'),
                user_id
            )
        )
        
        conn.commit()
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error updating exam with correct answers: {e}")
        return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش مراحل ایجاد آزمون"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # بررسی لغو عملیات
    if text == "❌ لغو":
        context.user_data.pop('exam_setup', None)
        
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            exam_setup = context.bot_data['user_exams'][user_id]
            if 'timer_message_id' in exam_setup:
                try:
                    await context.bot.unpin_chat_message(
                        chat_id=user_id,
                        message_id=exam_setup['timer_message_id']
                    )
                except Exception as e:
                    logger.error(f"Error unpinning timer message during cancel: {e}")
            context.bot_data['user_exams'].pop(user_id, None)
        
        await update.message.reply_text(
            "✅ عملیات لغو شد.",
            reply_markup=get_main_keyboard()
        )
        return
    
    if 'exam_setup' not in context.user_data:
        await update.message.reply_text(
            "لطفا ابتدا با دکمه '📝 ساخت آزمون جدید' یک آزمون جدید شروع کنید.",
            reply_markup=get_main_keyboard()
        )
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') == 'course_name':
        if not text:
            await update.message.reply_text("❌ نام درس نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
            return
            
        exam_setup['course_name'] = text
        exam_setup['step'] = 'topic_name'
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text("📖 لطفاً نام مبحث را وارد کنید:")
    
    elif exam_setup.get('step') == 'topic_name':
        if not text:
            await update.message.reply_text("❌ نام مبحث نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
            return
            
        exam_setup['topic_name'] = text
        exam_setup['step'] = 1
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text("🔢 لطفاً شماره اولین سوال را وارد کنید:")
    
    elif exam_setup.get('step') == 1:
        try:
            start_question = int(text)
            if start_question <= 0:
                await update.message.reply_text("❌ شماره سوال باید بزرگتر از صفر باشد.")
                return
                
            exam_setup['start_question'] = start_question
            exam_setup['step'] = 2
            context.user_data['exam_setup'] = exam_setup
            await update.message.reply_text("🔢 لطفاً شماره آخرین سوال را وارد کنید:")
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 2:
        try:
            end_question = int(text)
            start_question = exam_setup.get('start_question')
            
            if end_question <= start_question:
                await update.message.reply_text("❌ شماره آخرین سوال باید بزرگتر از اولین سوال باشد.")
                return
            
            total_questions_original = end_question - start_question + 1
            if total_questions_original > 200:
                await update.message.reply_text("❌ حداکثر تعداد سوالات مجاز 200 عدد است.")
                return
                
            exam_setup['end_question'] = end_question
            exam_setup['total_questions_original'] = total_questions_original
            exam_setup['step'] = 'pattern_selection'
            context.user_data['exam_setup'] = exam_setup
            
            keyboard = [
                [InlineKeyboardButton("1️⃣ همه سوالات (پشت سر هم)", callback_data="pattern_all")],
                [InlineKeyboardButton("2️⃣ یکی در میان (زوج/فرد)", callback_data="pattern_alternate")],
                [InlineKeyboardButton("3️⃣ دو تا در میان", callback_data="pattern_every_two")],
                [InlineKeyboardButton("4️⃣ سه تا در میان", callback_data="pattern_every_three")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "🔢 لطفاً الگوی سوالات را انتخاب کنید:",
                reply_markup=reply_markup
            )
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 3:
        try:
            exam_duration = int(text)
            if exam_duration < 0:
                await update.message.reply_text("❌ زمان آزمون نمی‌تواند منفی باشد.")
                return
                
            exam_setup['exam_duration'] = exam_duration
            exam_setup['step'] = 4
            exam_setup['answers'] = {}
            exam_setup['start_time'] = datetime.now()
            context.user_data['exam_setup'] = exam_setup
            
            if 'user_exams' not in context.bot_data:
                context.bot_data['user_exams'] = {}
            context.bot_data['user_exams'][user_id] = exam_setup
            
            if exam_duration > 0:
                job_name = f"timer_{user_id}"
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                context.job_queue.run_repeating(
                    update_timer,
                    interval=5,
                    first=1,
                    chat_id=user_id,
                    name=job_name
                )
            
            await show_questions_page(update, context, page=1)
            await show_pinned_timer(context, user_id, exam_setup)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پاسخ‌های اینلاین"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "ignore":
        return
    
    if 'exam_setup' not in context.user_data:
        await query.edit_message_text("⚠️ لطفا ابتدا یک آزمون جدید شروع کنید.")
        return
        
    exam_setup = context.user_data['exam_setup']
    
    if data.startswith("pattern_"):
        pattern_map = {
            'pattern_all': 'all',
            'pattern_alternate': 'alternate', 
            'pattern_every_two': 'every_two',
            'pattern_every_three': 'every_three'
        }
        pattern = pattern_map.get(data, 'all')

        exam_setup['question_pattern'] = pattern
        
        start_question = exam_setup.get('start_question')
        end_question = exam_setup.get('end_question')
        question_list = calculate_questions_by_pattern(start_question, end_question, pattern)
        total_questions = len(question_list)
        
        exam_setup['question_list'] = question_list
        exam_setup['total_questions'] = total_questions
        exam_setup['step'] = 3
        context.user_data['exam_setup'] = exam_setup
        
        course_name = exam_setup.get('course_name', 'نامعلوم')
        topic_name = exam_setup.get('topic_name', 'نامعلوم')
        
        summary_text = f"""
📋 خلاصه آزمون:

📚 درس: {course_name}
📖 مبحث: {topic_name}
🔢 محدوده سوالات: {start_question} تا {end_question}
🔢 الگو: {get_pattern_name(pattern)}
📝 تعداد سوالات: {total_questions}

⏰ لطفاً زمان آزمون را به دقیقه وارد کنید (اگر زمان محدود نمی‌خواهید، صفر وارد کنید):
"""
        await query.edit_message_text(summary_text)
        return
    
    elif data.startswith("ans_"):
        parts = data.split("_")
        question_num = int(parts[1])
        answer = int(parts[2])
        
        current_answer = exam_setup['answers'].get(str(question_num))
        
        if current_answer == answer:
            del exam_setup['answers'][str(question_num)]
        else:
            exam_setup['answers'][str(question_num)] = answer
        
        context.user_data['exam_setup'] = exam_setup
        
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        current_page = exam_setup.get('current_page', 1)
        await show_questions_page(update, context, current_page)
    
    elif data.startswith("correct_ans_"):
        parts = data.split("_")
        question_num = int(parts[2])
        answer = int(parts[3])
        
        current_answer = exam_setup['correct_answers'].get(str(question_num))
        
        if current_answer == answer:
            del exam_setup['correct_answers'][str(question_num)]
        else:
            exam_setup['correct_answers'][str(question_num)] = answer
        
        context.user_data['exam_setup'] = exam_setup
        
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        current_page = exam_setup.get('correct_answers_page', 1)
        await show_correct_answers_page(update, context, current_page)
    
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_questions_page(update, context, page)
    
    elif data.startswith("correct_page_"):
        page = int(data.split("_")[2])
        await show_correct_answers_page(update, context, page)
    
    elif data == "finish_exam":
        exam_setup['step'] = 'completion_choice'
        context.user_data['exam_setup'] = exam_setup
    
        start_time = exam_setup.get('start_time')
        elapsed_time = calculate_elapsed_time(start_time)
        exam_setup['elapsed_time'] = elapsed_time
    
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
    
    # استفاده از try-except برای مدیریت خطاهای ویرایش پیام
        try:
            await show_completion_options(update, context)
        except Exception as e:
            logger.error(f"Error showing completion options: {e}")
        # ارسال پیام جدید در صورت خطا
            await query.message.reply_text(
                "خطایی رخ داد. لطفاً مجدداً تلاش کنید.",
                reply_markup=get_main_keyboard()
        )
    
    elif data in ["enter_answers_now", "save_for_later", "back_to_exam"]:
        await handle_completion_choice(update, context, data)
    
    elif data == "finish_correct_answers":
        total_questions = exam_setup.get('total_questions')
        correct_answers = exam_setup.get('correct_answers', {})
        
        if len(correct_answers) != total_questions:
            await query.edit_message_text(
                text=f"❌ شما فقط برای {len(correct_answers)} سوال از {total_questions} سوال پاسخ صحیح وارد کرده‌اید.\n"
                     f"لطفاً پاسخ‌های صحیح باقی‌مانده را وارد کنید."
            )
            return
        
        user_answers = exam_setup.get('answers', {})
        question_list = exam_setup.get('question_list', [])
        
        correct_answers_list = []
        for question_num in question_list:
            str_question_num = str(question_num)
            correct_answer = correct_answers.get(str_question_num)
            if correct_answer is None:
                correct_answers_list.append('0')
            else:
                correct_answers_list.append(str(correct_answer))
        
        correct_answers_str = ''.join(correct_answers_list)
        
        if 'exam_id' in exam_setup:
            success = await update_exam_with_correct_answers(context, user_id, exam_setup, correct_answers_str)
        else:
            success = await save_completed_exam(user_id, exam_setup, correct_answers_str)
        
        if success:
            await show_final_results(update, context, exam_setup, correct_answers_str)
        else:
            await query.edit_message_text("❌ خطایی در ذخیره‌سازی نتایج رخ داد.")
    
    elif data == "switch_to_text_input":
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
        total_questions = exam_setup.get('total_questions')
        
        await query.edit_message_text(
            text=f"🔢 لطفاً پاسخ‌های صحیح را به صورت یک رشته عددی با {total_questions} رقم وارد کنید:\n\n"
                 f"📝 مثال: برای ۵ سوال: 12345\n"
                 f"💡 نکته: برای سوالات بی‌پاسخ از 0 استفاده کنید."
        )
    
    elif data.startswith("load_exam_"):
       exam_id = int(data.split("_")[2])
       await load_pending_exam(update, context, exam_id)
    
    elif data == "back_to_main":
        await query.edit_message_text(
            "🔙 بازگشت به منوی اصلی",
            reply_markup=get_main_keyboard()
        )

async def save_completed_exam(user_id: int, exam_setup: dict, correct_answers_str: str):
    """ذخیره آزمون تکمیل شده"""
    try:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            
            user_answers = exam_setup.get('answers', {})
            correct_answers = exam_setup.get('correct_answers', {})
            question_list = exam_setup.get('question_list', [])
            
            correct_questions = []
            wrong_questions = []
            unanswered_questions = []
            
            for question_num in question_list:
                str_question_num = str(question_num)
                correct_answer = correct_answers.get(str_question_num)
                user_answer = user_answers.get(str_question_num)
                
                if user_answer is None:
                    unanswered_questions.append(question_num)
                elif user_answer == correct_answer:
                    correct_questions.append(question_num)
                else:
                    wrong_questions.append(question_num)
            
            correct_count = len(correct_questions)
            wrong_count = len(wrong_questions)
            unanswered_count = len(unanswered_questions)
            total_questions = len(question_list)

            raw_score = correct_count
            penalty = wrong_count / 3.0
            final_score = max(0, raw_score - penalty)
            final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0
            
            jalali_date = get_jalali_date()
            tehran_time = get_tehran_time()
            
            cur.execute(
                """
                INSERT INTO exams 
                (user_id, course_name, topic_name, start_question, end_question, total_questions, 
                 exam_duration, elapsed_time, answers, correct_answers, score, wrong_questions, 
                 unanswered_questions, jalali_date, tehran_time, question_pattern, status, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    user_id,
                    exam_setup.get('course_name'),
                    exam_setup.get('topic_name'),
                    exam_setup.get('start_question'),
                    exam_setup.get('end_question'),
                    total_questions,
                    exam_setup.get('exam_duration'),
                    exam_setup.get('elapsed_time'),
                    str(user_answers),
                    correct_answers_str,
                    final_percentage,
                    str(wrong_questions),
                    str(unanswered_questions),
                    jalali_date,
                    tehran_time,
                    exam_setup.get('question_pattern', 'all'),
                    EXAM_STATUS['COMPLETED']
                )
            )
            
            conn.commit()
            cur.close()
            conn.close()
            return True
    except Exception as e:
        logger.error(f"Error saving completed exam: {e}")
    return False

async def show_final_results(update: Update, context: ContextTypes.DEFAULT_TYPE, exam_setup: dict, correct_answers_str: str):
    """نمایش نتایج نهایی آزمون"""
    query = update.callback_query
    user_id = query.from_user.id
    
    user_answers = exam_setup.get('answers', {})
    correct_answers = exam_setup.get('correct_answers', {})
    question_list = exam_setup.get('question_list', [])
    
    correct_questions = []
    wrong_questions = []
    unanswered_questions = []
    
    for question_num in question_list:
        str_question_num = str(question_num)
        correct_answer = correct_answers.get(str_question_num)
        user_answer = user_answers.get(str_question_num)
        
        if user_answer is None:
            unanswered_questions.append(question_num)
        elif user_answer == correct_answer:
            correct_questions.append(question_num)
        else:
            wrong_questions.append(question_num)
    
    correct_count = len(correct_questions)
    wrong_count = len(wrong_questions)
    unanswered_count = len(unanswered_questions)
    total_questions = len(question_list)

    percentage_without_penalty = (correct_count / total_questions) * 100 if total_questions > 0 else 0

    raw_score = correct_count
    penalty = wrong_count / 3.0
    final_score = max(0, raw_score - penalty)
    final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0

    elapsed_time = exam_setup.get('elapsed_time', 0)
    
    jalali_date = get_jalali_date()
    tehran_time = get_tehran_time()
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    question_pattern = exam_setup.get('question_pattern', 'all')
    
    result_text = f"""
📊 نتایج آزمون شما:

📚 درس: {course_name}
📖 مبحث: {topic_name}
🔢 الگو: {get_pattern_name(question_pattern)}
📅 تاریخ: {jalali_date}
⏰ زمان: {tehran_time}

✅ تعداد پاسخ صحیح: {correct_count}
❌ تعداد پاسخ اشتباه: {wrong_count}
⏸️ تعداد بی‌پاسخ: {unanswered_count}
📝 تعداد کل سوالات: {total_questions}
⏰ زمان صرف شده: {elapsed_time:.2f} دقیقه

📈 درصد بدون نمره منفی: {percentage_without_penalty:.2f}%
📉 درصد با نمره منفی: {final_percentage:.2f}%

🔢 سوالات صحیح: {', '.join(map(str, correct_questions)) if correct_questions else 'ندارد'}
🔢 سوالات غلط: {', '.join(map(str, wrong_questions)) if wrong_questions else 'ندارد'}
🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'ندارد'}

💡 نکته: هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد.
"""

    await query.edit_message_text(result_text)
    
    context.user_data.pop('exam_setup', None)
    if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
        exam_setup = context.bot_data['user_exams'][user_id]
        if 'timer_message_id' in exam_setup:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id']
                )
            except:
                pass
        context.bot_data['user_exams'].pop(user_id, None)
    
    job_name = f"timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده نتایج قبلی"""
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            if update.callback_query:
                await update.callback_query.message.reply_text("⚠️ در حال حاضر امکان دسترسی به تاریخچه نتایج وجود ندارد.")
            else:
                await update.message.reply_text("⚠️ در حال حاضر امکان دسترسی به تاریخچه نتایج وجود ندارد.")
            return
            
        cur = conn.cursor()
        
        cur.execute(
            """SELECT course_name, topic_name, created_at, score, start_question, end_question, 
                      exam_duration, elapsed_time, jalali_date, tehran_time, question_pattern, status 
               FROM exams WHERE user_id = %s AND status = %s 
               ORDER BY created_at DESC LIMIT 5""",
            (user_id, EXAM_STATUS['COMPLETED'])
        )
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            result_text = "📋 آخرین نتایج آزمون‌های شما:\n\n"
            for i, result in enumerate(results, 1):
                try:
                    course_name, topic_name, date, score, start_q, end_q, duration, elapsed, jalali_date, tehran_time, question_pattern, status = result
                    
                    duration = duration or 0
                    elapsed = elapsed or 0
                    score = score or 0
                    start_q = start_q or 0
                    end_q = end_q or 0
                    course_name = course_name or 'نامعلوم'
                    topic_name = topic_name or 'نامعلوم'
                    jalali_date = jalali_date or 'نامعلوم'
                    tehran_time = tehran_time or 'نامعلوم'
                    question_pattern = question_pattern or 'all'
                    
                    time_text = f"{elapsed:.1f} دقیقه از {duration} دقیقه" if duration and duration > 0 else f"{elapsed:.1f} دقیقه"
                    pattern_name = get_pattern_name(question_pattern)
                    
                    result_text += f"{i}. {course_name} - {topic_name}\n"
                    result_text += f"   سوالات {start_q}-{end_q} - الگو: {pattern_name}\n"
                    result_text += f"   زمان: {time_text}\n"
                    result_text += f"   نمره: {score:.2f}% - تاریخ: {jalali_date} {tehran_time}\n\n"
                
                except Exception as e:
                    logger.error(f"Error processing result {i}: {e}")
                    result_text += f"{i}. خطا در پردازش نتیجه\n\n"
        else:
            result_text = "📭 هیچ نتیجه‌ای برای نمایش وجود ندارد."
            
    except Exception as e:
        logger.error(f"Error retrieving results: {e}")
        result_text = "⚠️ خطایی در دریافت نتایج رخ داد."
    
    if update.callback_query:
        await update.callback_query.message.reply_text(result_text)
    else:
        await update.message.reply_text(result_text)

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """گزارش روزانه برای ادمین"""
    try:
        conn = get_db_connection()
        if conn is None:
            return
            
        cur = conn.cursor()
        
        today_jalali = get_jalali_date()
        
        # تعداد کاربران جدید امروز
        cur.execute("SELECT COUNT(*) FROM users WHERE jalali_date = %s", (today_jalali,))
        new_users_today = cur.fetchone()[0]
        
        # تعداد کل کاربران
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        
        # تعداد آزمون‌های امروز
        cur.execute("SELECT COUNT(*) FROM exams WHERE jalali_date = %s", (today_jalali,))
        exams_today = cur.fetchone()[0]
        
        # تعداد کل آزمون‌ها
        cur.execute("SELECT COUNT(*) FROM exams")
        total_exams = cur.fetchone()[0]
        
        # تعداد آزمون‌های ناتمام
        cur.execute("SELECT COUNT(*) FROM exams WHERE status = %s", (EXAM_STATUS['WAITING_ANSWERS'],))
        pending_exams = cur.fetchone()[0]
        
        # آمار الگوهای استفاده شده
        cur.execute("SELECT question_pattern, COUNT(*) FROM exams WHERE jalali_date = %s GROUP BY question_pattern", (today_jalali,))
        pattern_stats = cur.fetchall()
        
        cur.close()
        conn.close()
        
        pattern_text = ""
        for pattern, count in pattern_stats:
            pattern_name = get_pattern_name(pattern)
            pattern_text += f"   • {pattern_name}: {count} آزمون\n"
        
        report_text = f"""
📊 گزارش روزانه ربات

📅 تاریخ: {today_jalali}
👥 کاربران جدید امروز: {new_users_today}
👤 تعداد کل کاربران: {total_users}
📝 آزمون‌های امروز: {exams_today}
📚 تعداد کل آزمون‌ها: {total_exams}
⏳ آزمون‌های ناتمام: {pending_exams}

🔢 آمار الگوهای سوالات:
{pattern_text if pattern_text else "   • امروز هیچ آزمونی ثبت نشده"}

💫 ربات در حال فعالیت است...
"""
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=report_text
        )
        
    except Exception as e:
        logger.error(f"Error sending daily report: {e}")

def main():
    """تابع اصلی"""
    if not init_db():
        logger.warning("Database initialization failed. The bot will work without database support.")
    
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CommandHandler("pending", show_pending_exams))
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CommandHandler("about", show_about))
    
    application.add_handler(CallbackQueryHandler(handle_button, pattern="^(new_exam|results|pending_exams|help)$"))
    application.add_handler(CallbackQueryHandler(handle_answer, pattern="^(pattern_|ans_|correct_ans_|page_|correct_page_|finish_exam|finish_correct_answers|switch_to_text_input|enter_answers_now|save_for_later|back_to_exam|load_exam_|back_to_main|ignore)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_message))
    
    # تنظیم job برای گزارش روزانه
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_daily(
            send_daily_report,
            time=time(hour=8, minute=0, second=0, tzinfo=TEHRAN_TZ),
            days=(0, 1, 2, 3, 4, 5, 6),
            name="daily_report"
        )
    
    logger.info("Bot started with enhanced features and pending exams support...")
    application.run_polling()

if __name__ == "__main__":
    main()
