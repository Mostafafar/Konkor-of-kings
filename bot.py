import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
import jdatetime  # برای تاریخ شمسی
import pytz  # برای منطقه زمانی

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توکن ربات
TOKEN = "8211286788:AAEf0nacvSZy7uXfUmcxNDkGquujQuvYzbE"

# آیدی ادمین (جایگزین کنید با آیدی عددی خود)
ADMIN_ID = 6680287530  # تغییر به آیدی عددی ادمین

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
QUESTIONS_PER_PAGE = 10  # حداکثر ۱۰ سوال در هر صفحه

def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

# ایجاد جدول در دیتابیس
def init_db():
    try:
        conn = get_db_connection()
        if conn is None:
            logger.error("Failed to connect to database for initialization")
            return False
            
        cur = conn.cursor()
        
        # ایجاد جدول اگر وجود ندارد
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
                tehran_time TEXT
            )
        ''')
        
        # ایجاد جدول برای آمار کاربران
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                exam_count INTEGER DEFAULT 0,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # بررسی و اضافه کردن ستون‌های جدید اگر وجود ندارند
        columns_to_add = [
            ('course_name', 'TEXT'),
            ('topic_name', 'TEXT'),
            ('jalali_date', 'TEXT'),
            ('tehran_time', 'TEXT'),
            ('exam_duration', 'INTEGER DEFAULT 0'),
            ('elapsed_time', 'REAL DEFAULT 0')
        ]
        
        for column_name, column_type in columns_to_add:
            try:
                cur.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='exams' AND column_name='{column_name}'
                """)
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE exams ADD COLUMN {column_name} {column_type}")
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

# دریافت تاریخ و زمان تهران
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

# ثبت یا به روزرسانی کاربر
async def update_user_stats(user_data):
    try:
        conn = get_db_connection()
        if conn is None:
            return False
            
        cur = conn.cursor()
        
        cur.execute('''
            INSERT INTO user_stats (user_id, username, first_name, last_name, last_seen, exam_count)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, 0)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                last_seen = EXCLUDED.last_seen
        ''', (
            user_data['id'],
            user_data.get('username'),
            user_data.get('first_name'),
            user_data.get('last_name')
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error updating user stats: {e}")
        return False

# افزایش تعداد آزمون‌های کاربر
async def increment_user_exam_count(user_id):
    try:
        conn = get_db_connection()
        if conn is None:
            return False
            
        cur = conn.cursor()
        
        cur.execute('''
            UPDATE user_stats 
            SET exam_count = exam_count + 1 
            WHERE user_id = %s
        ''', (user_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error incrementing user exam count: {e}")
        return False

# ارسال اطلاعات کاربر جدید به ادمین
async def notify_admin_new_user(context: ContextTypes.DEFAULT_TYPE, user_data):
    try:
        user_info = f"""
👤 کاربر جدید از بات استفاده کرد:

🆔 آیدی: {user_data['id']}
👤 نام: {user_data.get('first_name', 'نامعلوم')}
📛 نام خانوادگی: {user_data.get('last_name', 'نامعلوم')}
🔗 نام کاربری: @{user_data.get('username', 'نامعلوم')}
📅 تاریخ: {get_jalali_date()}
⏰ زمان: {get_tehran_time()}
        """
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=user_info
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")

# ارسال گزارش روزانه به ادمین
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        if conn is None:
            return
            
        cur = conn.cursor()
        
        # تاریخ امروز
        today = get_jalali_date()
        
        # تعداد آزمون‌های امروز
        cur.execute(
            "SELECT COUNT(*) FROM exams WHERE jalali_date = %s",
            (today,)
        )
        today_exams = cur.fetchone()[0] or 0
        
        # تعداد کاربران فعال امروز
        cur.execute(
            "SELECT COUNT(DISTINCT user_id) FROM exams WHERE jalali_date = %s",
            (today,)
        )
        active_users = cur.fetchone()[0] or 0
        
        # کل کاربران
        cur.execute("SELECT COUNT(*) FROM user_stats")
        total_users = cur.fetchone()[0] or 0
        
        # کاربران جدید امروز
        cur.execute(
            "SELECT COUNT(*) FROM user_stats WHERE DATE(first_seen) = DATE(CURRENT_TIMESTAMP)"
        )
        new_users = cur.fetchone()[0] or 0
        
        cur.close()
        conn.close()
        
        report_text = f"""
📊 گزارش روزانه بات آزمون‌ساز

📅 تاریخ: {today}
⏰ زمان: {get_tehran_time()}

📈 آمار امروز:
• 🎯 تعداد آزمون‌های ساخته شده: {today_exams}
• 👥 کاربران فعال: {active_users}
• 🆕 کاربران جدید: {new_users}

📋 آمار کلی:
• 👥 کل کاربران: {total_users}

🎉 امروز یک روز پربار بود!
        """
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=report_text
        )
        
    except Exception as e:
        logger.error(f"Error sending daily report: {e}")

# تنظیم منوی دستورات
async def set_bot_commands(application: Application):
    commands = [
        BotCommand("start", "شروع مجدد ربات 🚀"),
        BotCommand("new_exam", "ساخت پاسخبرگ جدید 📝"),
        BotCommand("results", "مشاهده نتایج قبلی 📊"),
        BotCommand("help", "راهنمای استفاده از ربات ❓")
    ]
    await application.bot.set_my_commands(commands)

# مدیریت دستور start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # ذخیره اطلاعات کاربر
    user_data = {
        'id': user_id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name
    }
    
    # به روزرسانی آمار کاربر
    await update_user_stats(user_data)
    
    # ارسال اطلاع به ادمین (فقط برای کاربران جدید)
    if context.user_data.get('is_new_user', True):
        await notify_admin_new_user(context, user_data)
        context.user_data['is_new_user'] = False
    
    # متن زیبای خوش‌آمدگویی
    welcome_text = """
🎉 **به بات ساخت پاسخبرگ خوش آمدید!** 🎉

📚 **ویژگی‌های بات:**
• ✅ ساخت پاسخبرگ حرفه‌ای
• ⏱️ زمان‌بندی آزمون
• 📊 محاسبه نمره با نمره منفی
• 💾 ذخیره نتایج
• 📈 گزارش‌گیری پیشرفته

🎯 **برای شروع آزمون جدید، روی دکمه زیر کلیک کنید:**
    """
    
    # ایجاد کیبورد برای دسترسی آسان
    keyboard = [
        [InlineKeyboardButton("🎯 شروع آزمون جدید", callback_data="new_exam")],
        [InlineKeyboardButton("📊 مشاهده نتایج قبلی", callback_data="results")],
        [InlineKeyboardButton("ℹ️ راهنمای استفاده", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# مدیریت دستور help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 **راهنمای استفاده از بات**

🎯 **دستورات اصلی:**
• /start - شروع مجدد ربات
• /new_exam - ساخت پاسخبرگ جدید
• /results - مشاهده نتایج قبلی
• /help - نمایش این راهنما

📝 **مراحل ساخت آزمون:**
1️⃣ وارد کردن نام درس
2️⃣ وارد کردن نام مبحث
3️⃣ مشخص کردن محدوده سوالات
4️⃣ تعیین زمان آزمون (اختیاری)
5️⃣ پاسخ‌دهی به سوالات
6️⃣ وارد کردن پاسخ‌های صحیح
7️⃣ دریافت نتایج و تحلیل

⏰ **امکانات ویژه:**
• تایمر هوشمند
• صفحه‌بندی سوالات
• محاسبه خودکار نمره
• ذخیره تاریخچه
• گزارش‌گیری دقیق

💡 **نکته:** هر ۳ پاسخ اشتباه، معادل ۱ پاسخ صحیح نمره منفی دارد.
    """
    
    keyboard = [
        [InlineKeyboardButton("🎯 شروع آزمون جدید", callback_data="new_exam")],
        [InlineKeyboardButton("📊 نتایج قبلی", callback_data="results")],
        [InlineKeyboardButton("🏠 بازگشت به خانه", callback_data="start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')

# مدیریت callback query برای دکمه‌ها
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "new_exam":
        await new_exam(update, context)
    elif query.data == "results":
        await show_results(update, context)
    elif query.data == "help":
        await help_command(update, context)
    elif query.data == "start":
        await start(update, context)

# ایجاد آزمون جدید
async def new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # پاک کردن وضعیت قبلی
    context.user_data.pop('exam_setup', None)
    
    # ایجاد وضعیت جدید
    context.user_data['exam_setup'] = {'step': 'course_name'}
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "📚 لطفاً نام درس را وارد کنید:"
        )
    else:
        await update.message.reply_text(
            "📚 لطفاً نام درس را وارد کنید:"
        )

# محاسبه تعداد صفحات
def calculate_total_pages(total_questions):
    return (total_questions + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE

# نمایش سوالات به صورت صفحه‌بندی شده
async def show_questions_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    exam_setup = context.user_data['exam_setup']
    start_question = exam_setup.get('start_question')
    end_question = exam_setup.get('end_question')
    user_answers = exam_setup.get('answers', {})
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    total_questions = exam_setup.get('total_questions')
    
    # محاسبه صفحات
    total_pages = calculate_total_pages(total_questions)
    page = max(1, min(page, total_pages))
    
    # محاسبه محدوده سوالات برای این صفحه
    start_idx = (page - 1) * QUESTIONS_PER_PAGE
    end_idx = min(start_idx + QUESTIONS_PER_PAGE, total_questions)
    
    message_text = f"📚 درس: {course_name}\n"
    message_text += f"📖 مبحث: {topic_name}\n"
    message_text += f"📄 صفحه {page} از {total_pages}\n\n"
    message_text += "📝 لطفاً به سوالات پاسخ دهید:\n\n"
    
    # ایجاد دکمه‌های اینلاین برای سوالات این صفحه
    keyboard = []
    
    for question_num in range(start_question + start_idx, start_question + end_idx):
        # وضعیت پاسخ فعلی
        current_answer = user_answers.get(str(question_num))
        status = f" ✅ (گزینه {current_answer})" if current_answer else ""
        
        # ایجاد دکمه‌های گزینه‌ها برای هر سوال با شماره سوال
        question_buttons = []
        # دکمه شماره سوال (غیرفعال)
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
    # اگر این گزینه قبلاً انتخاب شده، علامت ✅ نشان داده شود
            if current_answer == option:
                button_text = f"{option} ✅"
            else:
                button_text = str(option)  
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    # دکمه‌های ناوبری بین صفحات
    navigation_buttons = []
    if total_pages > 1:
        if page > 1:
            navigation_buttons.append(InlineKeyboardButton("◀️ صفحه قبلی", callback_data=f"page_{page-1}"))
        if page < total_pages:
            navigation_buttons.append(InlineKeyboardButton("صفحه بعدی ▶️", callback_data=f"page_{page+1}"))
        
        if navigation_buttons:
            keyboard.append(navigation_buttons)
    
    # اضافه کردن دکمه اتمام آزمون
    keyboard.append([InlineKeyboardButton("🎯 اتمام آزمون و ارسال پاسخ‌ها", callback_data="finish_exam")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ذخیره شماره صفحه فعلی
    exam_setup['current_page'] = page
    context.user_data['exam_setup'] = exam_setup
    
    # اگر قبلاً پیامی ارسال شده، آن را ویرایش کن
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
    
    # ارسال پیام جدید و ذخیره ID آن
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        reply_markup=reply_markup
    )
    exam_setup['exam_message_id'] = message.message_id
    context.user_data['exam_setup'] = exam_setup

# نمایش سوالات برای وارد کردن پاسخ‌های صحیح
async def show_correct_answers_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    exam_setup = context.user_data['exam_setup']
    start_question = exam_setup.get('start_question')
    end_question = exam_setup.get('end_question')
    correct_answers = exam_setup.get('correct_answers', {})
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    total_questions = exam_setup.get('total_questions')
    
    # محاسبه صفحات
    total_pages = calculate_total_pages(total_questions)
    page = max(1, min(page, total_pages))
    
    # محاسبه محدوده سوالات برای این صفحه
    start_idx = (page - 1) * QUESTIONS_PER_PAGE
    end_idx = min(start_idx + QUESTIONS_PER_PAGE, total_questions)
    
    # محاسبه تعداد پاسخ‌های وارد شده
    answered_count = len(correct_answers)
    
    message_text = f"📚 درس: {course_name}\n"
    message_text += f"📖 مبحث: {topic_name}\n"
    message_text += f"📄 صفحه {page} از {total_pages}\n"
    message_text += f"✅ پاسخ‌های وارد شده: {answered_count}/{total_questions}\n\n"
    message_text += "لطفاً پاسخ‌های صحیح را برای سوالات زیر انتخاب کنید:\n\n"
    
    # ایجاد دکمه‌های اینلاین برای سوالات این صفحه
    keyboard = []
    
    for question_num in range(start_question + start_idx, start_question + end_idx):
        # وضعیت پاسخ صحیح فعلی
        current_answer = correct_answers.get(str(question_num))
        
        # ایجاد دکمه‌های گزینه‌ها برای هر سوال با شماره سوال
        question_buttons = []
        # دکمه شماره سوال (غیرفعال)
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
    # اگر این گزینه قبلاً انتخاب شده، علامت ✅ نشان داده شود
            if current_answer == option:
                button_text = f"{option} ✅"
            else:
                button_text = str(option)
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"correct_ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    # دکمه‌های ناوبری بین صفحات
    navigation_buttons = []
    if total_pages > 1:
        if page > 1:
            navigation_buttons.append(InlineKeyboardButton("◀️ صفحه قبلی", callback_data=f"correct_page_{page-1}"))
        if page < total_pages:
            navigation_buttons.append(InlineKeyboardButton("صفحه بعدی ▶️", callback_data=f"correct_page_{page+1}"))
        
        if navigation_buttons:
            keyboard.append(navigation_buttons)
    
    # اضافه کردن دکمه اتمام وارد کردن پاسخ‌های صحیح (فقط اگر همه سوالات پاسخ داشته باشند)
    if answered_count == total_questions:
        keyboard.append([InlineKeyboardButton("✅ اتمام وارد کردن پاسخ‌های صحیح", callback_data="finish_correct_answers")])
    else:
        keyboard.append([InlineKeyboardButton("⏳ لطفاً برای همه سوالات پاسخ وارد کنید", callback_data="ignore")])
    
    # اضافه کردن دکمه برای تغییر روش وارد کردن پاسخ‌ها
    keyboard.append([InlineKeyboardButton("🔢 وارد کردن پاسخ‌ها به صورت رشته عددی", callback_data="switch_to_text_input")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ذخیره شماره صفحه فعلی برای پاسخ‌های صحیح
    exam_setup['correct_answers_page'] = page
    context.user_data['exam_setup'] = exam_setup
    
    # اگر قبلاً پیامی ارسال شده، آن را ویرایش کن
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
    
    # ارسال پیام جدید و ذخیره ID آن
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

# ایجاد نوار پیشرفت
def create_progress_bar(percentage):
    filled = min(10, int(percentage / 10))
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage:.1f}%"

# تایمر با پیام پین شده
async def show_pinned_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, exam_setup: dict):
    exam_duration = exam_setup.get('exam_duration', 0)
    start_time = exam_setup.get('start_time')
    
    if not exam_duration or not start_time:
        return
    
    elapsed_time = (datetime.now() - start_time).total_seconds()
    remaining_time = max(0, exam_duration * 60 - elapsed_time)
    minutes = int(remaining_time // 60)
    seconds = int(remaining_time % 60)
    
    # ایجاد اعلان تایمر پیشرفته
    progress_percent = (elapsed_time / (exam_duration * 60)) * 100
    progress_bar = create_progress_bar(progress_percent)
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    
    # فقط نوار پیشرفت و زمان باقیمانده نمایش داده شود
    timer_text = f"📚 {course_name} - {topic_name}\n⏳ باقیمانده: {minutes:02d}:{seconds:02d}\n{progress_bar}"
    
    # ارسال یا ویرایش پیام تایمر
    if 'timer_message_id' in exam_setup:
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=exam_setup['timer_message_id'],
                text=timer_text,
                parse_mode='Markdown'
            )
            # پین کردن پیام
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
            # پین کردن پیام
            try:
                await context.bot.pin_chat_message(
                    chat_id=user_id,
                    message_id=message.message_id,
                    disable_notification=True
                )
            except:
                pass
            # ذخیره در bot_data
            if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
                context.bot_data['user_exams'][user_id] = exam_setup
        except Exception as e:
            logger.error(f"Error sending timer message: {e}")

# تایمر برای به روزرسانی زمان
async def update_timer(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.chat_id
    
    # دریافت داده‌های کاربر از bot_data
    if 'user_exams' not in context.bot_data:
        return
    
    if user_id not in context.bot_data['user_exams']:
        return
    
    exam_setup = context.bot_data['user_exams'][user_id]
    
    if exam_setup.get('step') != 4:  # اگر در مرحله آزمون نیست
        return
    
    exam_duration = exam_setup.get('exam_duration', 0)
    start_time = exam_setup.get('start_time')
    
    if not exam_duration or not start_time:
        return
    
    # محاسبه زمان باقیمانده
    elapsed_time = (datetime.now() - start_time).total_seconds()
    remaining_time = max(0, exam_duration * 60 - elapsed_time)
    
    # اگر زمان تمام شد
    if remaining_time <= 0:
        await finish_exam_auto(context, user_id)
        return
    
    # نمایش تایمر پین شده
    await show_pinned_timer(context, user_id, exam_setup)

# اتمام خودکار آزمون وقتی زمان تمام شد
async def finish_exam_auto(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if 'user_exams' not in context.bot_data or user_id not in context.bot_data['user_exams']:
        return
    
    exam_setup = context.bot_data['user_exams'][user_id]
    
    # تغییر وضعیت به انتظار برای پاسخ‌های صحیح
    exam_setup['step'] = 'waiting_for_correct_answers_inline'
    exam_setup['correct_answers'] = {}
    context.bot_data['user_exams'][user_id] = exam_setup
    
    # محاسبه زمان صرف شده
    start_time = exam_setup.get('start_time')
    elapsed_time = calculate_elapsed_time(start_time)
    exam_setup['elapsed_time'] = elapsed_time
    
    # حذف job تایمر
    job_name = f"timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    
    total_questions = exam_setup.get('total_questions')
    answered_count = len(exam_setup.get('answers', {}))
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    
    # ارسال پیام اتمام زمان
    try:
        message = await context.bot.send_message(
            chat_id=user_id,
            text=f"📚 {course_name} - {topic_name}\n"
                 f"⏰ زمان آزمون به پایان رسید!\n"
                 f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
                 f"لطفاً پاسخ‌های صحیح را با استفاده از دکمه‌های زیر وارد کنید:"
        )
        
        # نمایش اولین صفحه پاسخ‌های صحیح
        await show_correct_answers_page(context, context, page=1)
        
        # آنپین کردن پیام تایمر
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

# محاسبه زمان صرف شده
def calculate_elapsed_time(start_time):
    """محاسبه زمان سپری شده از شروع آزمون"""
    if not start_time:
        return 0
    elapsed = datetime.now() - start_time
    return round(elapsed.total_seconds() / 60, 2)  # بازگشت زمان بر حسب دقیقه

# پردازش مراحل ایجاد آزمون
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if 'exam_setup' not in context.user_data:
        await update.message.reply_text("لطفا ابتدا با دستور /new_exam یک آزمون جدید شروع کنید.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') == 'course_name':
        if not text:
            await update.message.reply_text("❌ نام درس نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
            return
            
        exam_setup['course_name'] = text
        exam_setup['step'] = 'topic_name'
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text(
            "📖 لطفاً نام مبحث را وارد کنید:"
        )
    
    elif exam_setup.get('step') == 'topic_name':
        if not text:
            await update.message.reply_text("❌ نام مبحث نمی‌تواند خالی باشد. لطفاً مجدداً وارد کنید:")
            return
            
        exam_setup['topic_name'] = text
        exam_setup['step'] = 1
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text(
            "🔢 لطفاً شماره اولین سوال را وارد کنید:"
        )
    
    elif exam_setup.get('step') == 1:
        try:
            start_question = int(text)
            if start_question <= 0:
                await update.message.reply_text("❌ شماره سوال باید بزرگتر از صفر باشد.")
                return
                
            exam_setup['start_question'] = start_question
            exam_setup['step'] = 2
            context.user_data['exam_setup'] = exam_setup
            await update.message.reply_text(
                "🔢 لطفاً شماره آخرین سوال را وارد کنید:"
            )
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 2:
        try:
            end_question = int(text)
            start_question = exam_setup.get('start_question')
            
            if end_question <= start_question:
                await update.message.reply_text("❌ شماره آخرین سوال باید بزرگتر از اولین سوال باشد.")
                return
            
            total_questions = end_question - start_question + 1
            if total_questions > 200:
                await update.message.reply_text("❌ حداکثر تعداد سوالات مجاز 200 عدد است.")
                return
                
            exam_setup['end_question'] = end_question
            exam_setup['total_questions'] = total_questions
            exam_setup['step'] = 3
            context.user_data['exam_setup'] = exam_setup
            
            await update.message.reply_text(
                "⏰ لطفاً مدت زمان آزمون را به دقیقه وارد کنید (0 برای بدون محدودیت):"
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
            
            # ذخیره در bot_data برای دسترسی در jobها
            if 'user_exams' not in context.bot_data:
                context.bot_data['user_exams'] = {}
            context.bot_data['user_exams'][user_id] = exam_setup
            
            # شروع تایمر اگر زمان مشخص شده
            if exam_duration > 0:
                job_name = f"timer_{user_id}"
                # حذف jobهای قبلی
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                # ایجاد job جدید برای تایمر
                context.job_queue.run_repeating(
                    update_timer,
                    interval=5,  # به روزرسانی هر 5 ثانیه
                    first=1,
                    chat_id=user_id,
                    name=job_name
                )
            
            # نمایش اولین صفحه سوالات
            await show_questions_page(update, context, page=1)
            
            # نمایش تایمر پین شده
            await show_pinned_timer(context, user_id, exam_setup)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 'waiting_for_correct_answers':
        # این حالت برای پشتیبانی از حالت قدیمی (رشته عددی) نگه داشته شده است
        total_questions = exam_setup.get('total_questions')
        
        # حذف فاصله و کاراکترهای غیرعددی
        cleaned_text = ''.join(filter(str.isdigit, text))
        
        if len(cleaned_text) != total_questions:
            await update.message.reply_text(
                f"❌ رشته ارسالی باید شامل {total_questions} عدد باشد. شما {len(cleaned_text)} عدد ارسال کرده‌اید.\n"
                f"لطفاً مجدداً رشته عددی را وارد کنید:"
            )
            return
        
        # ذخیره پاسخ‌های صحیح
        correct_answers = {}
        for i, answer in enumerate(cleaned_text):
            question_num = exam_setup['start_question'] + i
            correct_answers[str(question_num)] = int(answer)
        
        exam_setup['correct_answers'] = correct_answers
        context.user_data['exam_setup'] = exam_setup
        
        # محاسبه نتایج
        await calculate_results(update, context)

# محاسبه نتایج آزمون
async def calculate_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam_setup = context.user_data['exam_setup']
    user_answers = exam_setup.get('answers', {})
    correct_answers = exam_setup.get('correct_answers', {})
    
    # محاسبه آمار
    correct_count = 0
    wrong_count = 0
    unanswered_count = 0
    wrong_questions = []
    unanswered_questions = []
    
    for question_num in range(exam_setup['start_question'], exam_setup['end_question'] + 1):
        str_question_num = str(question_num)
        user_answer = user_answers.get(str_question_num)
        correct_answer = correct_answers.get(str_question_num)
        
        if user_answer is None:
            unanswered_count += 1
            unanswered_questions.append(question_num)
        elif user_answer == correct_answer:
            correct_count += 1
        else:
            wrong_count += 1
            wrong_questions.append(question_num)
    
    # محاسبه نمره (هر ۳ غلط = ۱ نمره منفی)
    score = max(0, correct_count - (wrong_count // 3))
    
    # ذخیره نتایج
    exam_setup['score'] = score
    exam_setup['correct_count'] = correct_count
    exam_setup['wrong_count'] = wrong_count
    exam_setup['unanswered_count'] = unanswered_count
    exam_setup['wrong_questions'] = wrong_questions
    exam_setup['unanswered_questions'] = unanswered_questions
    
    # ذخیره در دیتابیس
    await save_exam_to_db(update.effective_user.id, exam_setup)
    
    # نمایش نتایج
    await show_results_message(update, context, exam_setup)

# ذخیره آزمون در دیتابیس
async def save_exam_to_db(user_id: int, exam_setup: dict):
    try:
        conn = get_db_connection()
        if conn is None:
            return False
            
        cur = conn.cursor()
        
        # تبدیل داده‌ها به فرمت مناسب
        answers_str = str(exam_setup.get('answers', {}))
        correct_answers_str = str(exam_setup.get('correct_answers', {}))
        wrong_questions_str = str(exam_setup.get('wrong_questions', []))
        unanswered_questions_str = str(exam_setup.get('unanswered_questions', []))
        
        # دریافت تاریخ و زمان تهران
        jalali_date = get_jalali_date()
        tehran_time = get_tehran_time()
        
        cur.execute('''
            INSERT INTO exams 
            (user_id, course_name, topic_name, start_question, end_question, total_questions,
             exam_duration, elapsed_time, answers, correct_answers, score, wrong_questions, 
             unanswered_questions, jalali_date, tehran_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            user_id,
            exam_setup.get('course_name'),
            exam_setup.get('topic_name'),
            exam_setup.get('start_question'),
            exam_setup.get('end_question'),
            exam_setup.get('total_questions'),
            exam_setup.get('exam_duration', 0),
            exam_setup.get('elapsed_time', 0),
            answers_str,
            correct_answers_str,
            exam_setup.get('score', 0),
            wrong_questions_str,
            unanswered_questions_str,
            jalali_date,
            tehran_time
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        
        # افزایش تعداد آزمون‌های کاربر
        await increment_user_exam_count(user_id)
        
        logger.info(f"Exam saved for user {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error saving exam to database: {e}")
        return False

# نمایش پیام نتایج
async def show_results_message(update: Update, context: ContextTypes.DEFAULT_TYPE, exam_setup: dict):
    user_id = update.effective_user.id
    
    # ایجاد متن نتایج
    results_text = f"""
🎉 **نتایج آزمون شما** 🎉

📚 **درس:** {exam_setup.get('course_name', 'نامعلوم')}
📖 **مبحث:** {exam_setup.get('topic_name', 'نامعلوم')}
📊 **تعداد سوالات:** {exam_setup.get('total_questions')}

✅ **پاسخ‌های صحیح:** {exam_setup.get('correct_count')}
❌ **پاسخ‌های غلط:** {exam_setup.get('wrong_count')}
⏭️ **پاسخ نداده:** {exam_setup.get('unanswered_count')}

🎯 **نمره نهایی:** {exam_setup.get('score')} از {exam_setup.get('total_questions')}

⏰ **زمان صرف شده:** {exam_setup.get('elapsed_time', 0):.1f} دقیقه
📅 **تاریخ:** {get_jalali_date()}
🕒 **ساعت:** {get_tehran_time()}
    """
    
    # ایجاد دکمه‌های پایین صفحه
    keyboard = [
        [InlineKeyboardButton("📝 آزمون جدید", callback_data="new_exam")],
        [InlineKeyboardButton("📊 نتایج قبلی", callback_data="results")],
        [InlineKeyboardButton("🏠 صفحه اصلی", callback_data="start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ارسال پیام نتایج
    if update.callback_query:
        await update.callback_query.message.reply_text(results_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await context.bot.send_message(user_id, results_text, reply_markup=reply_markup, parse_mode='Markdown')

# نمایش نتایج قبلی
async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            await update.message.reply_text("❌ خطا در اتصال به دیتابیس.")
            return
            
        cur = conn.cursor()
        
        # دریافت ۱۰ آزمون آخر کاربر
        cur.execute('''
            SELECT course_name, topic_name, score, total_questions, jalali_date, tehran_time
            FROM exams 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT 10
        ''', (user_id,))
        
        exams = cur.fetchall()
        cur.close()
        conn.close()
        
        if not exams:
            if update.callback_query:
                await update.callback_query.message.reply_text("📭 هیچ آزمونی ثبت نشده است.")
            else:
                await update.message.reply_text("📭 هیچ آزمونی ثبت نشده است.")
            return
        
        # ایجاد متن نتایج
        results_text = "📊 **نتایج آزمون‌های قبلی شما:**\n\n"
        
        for i, exam in enumerate(exams, 1):
            course_name, topic_name, score, total_questions, jalali_date, tehran_time = exam
            results_text += f"{i}. **{course_name}** - {topic_name}\n"
            results_text += f"   🎯 نمره: {score}/{total_questions}\n"
            results_text += f"   📅 {jalali_date} - 🕒 {tehran_time}\n\n"
        
        # ایجاد دکمه‌های پایین صفحه
        keyboard = [
            [InlineKeyboardButton("📝 آزمون جدید", callback_data="new_exam")],
            [InlineKeyboardButton("🏠 صفحه اصلی", callback_data="start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.message.reply_text(results_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(results_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error fetching results: {e}")
        error_text = "❌ خطا در دریافت نتایج. لطفاً بعداً تلاش کنید."
        if update.callback_query:
            await update.callback_query.message.reply_text(error_text)
        else:
            await update.message.reply_text(error_text)

# مدیریت کلیک روی دکمه‌های اینلاین
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # دکمه‌های نادیده گرفته شده
    if data == "ignore":
        return
    
    # مدیریت دکمه‌های پاسخ‌دهی
    elif data.startswith("ans_"):
        await handle_answer_selection(update, context, data)
    
    # مدیریت دکمه‌های پاسخ صحیح
    elif data.startswith("correct_ans_"):
        await handle_correct_answer_selection(update, context, data)
    
    # مدیریت صفحات
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await show_questions_page(update, context, page)
    
    # مدیریت صفحات پاسخ صحیح
    elif data.startswith("correct_page_"):
        page = int(data.split("_")[2])
        await show_correct_answers_page(update, context, page)
    
    # اتمام آزمون
    elif data == "finish_exam":
        await finish_exam_manual(update, context)
    
    # اتمام وارد کردن پاسخ‌های صحیح
    elif data == "finish_correct_answers":
        await finish_correct_answers(update, context)
    
    # تغییر به حالت متنی برای وارد کردن پاسخ‌ها
    elif data == "switch_to_text_input":
        await switch_to_text_input(update, context)

# مدیریت انتخاب پاسخ توسط کاربر
async def handle_answer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    
    if 'exam_setup' not in context.user_data:
        await update.callback_query.message.reply_text("❌ خطا در دریافت اطلاعات آزمون.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') != 4:
        await update.callback_query.message.reply_text("❌ آزمون فعالی وجود ندارد.")
        return
    
    # استخراج اطلاعات از دیتا
    parts = data.split("_")
    question_num = int(parts[2])
    selected_answer = int(parts[3])
    
    # ذخیره پاسخ کاربر
    if 'answers' not in exam_setup:
        exam_setup['answers'] = {}
    
    exam_setup['answers'][str(question_num)] = selected_answer
    context.user_data['exam_setup'] = exam_setup
    
    # به روزرسانی صفحه فعلی
    current_page = exam_setup.get('current_page', 1)
    await show_questions_page(update, context, current_page)

# مدیریت انتخاب پاسخ صحیح
async def handle_correct_answer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    
    if 'exam_setup' not in context.user_data:
        await update.callback_query.message.reply_text("❌ خطا در دریافت اطلاعات آزمون.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') != 'waiting_for_correct_answers_inline':
        await update.callback_query.message.reply_text("❌ مرحله وارد کردن پاسخ‌های صحیح فعال نیست.")
        return
    
    # استخراج اطلاعات از دیتا
    parts = data.split("_")
    question_num = int(parts[2])
    correct_answer = int(parts[3])
    
    # ذخیره پاسخ صحیح
    if 'correct_answers' not in exam_setup:
        exam_setup['correct_answers'] = {}
    
    exam_setup['correct_answers'][str(question_num)] = correct_answer
    context.user_data['exam_setup'] = exam_setup
    
    # به روزرسانی صفحه فعلی
    current_page = exam_setup.get('correct_answers_page', 1)
    await show_correct_answers_page(update, context, current_page)

# اتمام دستی آزمون توسط کاربر
async def finish_exam_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if 'exam_setup' not in context.user_data:
        await update.callback_query.message.reply_text("❌ آزمون فعالی وجود ندارد.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') != 4:
        await update.callback_query.message.reply_text("❌ آزمون فعالی وجود ندارد.")
        return
    
    # تغییر وضعیت به انتظار برای پاسخ‌های صحیح
    exam_setup['step'] = 'waiting_for_correct_answers_inline'
    exam_setup['correct_answers'] = {}
    context.user_data['exam_setup'] = exam_setup
    
    # محاسبه زمان صرف شده
    start_time = exam_setup.get('start_time')
    elapsed_time = calculate_elapsed_time(start_time)
    exam_setup['elapsed_time'] = elapsed_time
    
    # حذف job تایمر
    job_name = f"timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    
    total_questions = exam_setup.get('total_questions')
    answered_count = len(exam_setup.get('answers', {}))
    
    course_name = exam_setup.get('course_name', 'نامعلوم')
    topic_name = exam_setup.get('topic_name', 'نامعلوم')
    
    # ارسال پیام تأیید
    try:
        message = await update.callback_query.message.reply_text(
            f"📚 {course_name} - {topic_name}\n"
            f"✅ آزمون با موفقیت به پایان رسید!\n"
            f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
            f"لطفاً پاسخ‌های صحیح را با استفاده از دکمه‌های زیر وارد کنید:"
        )
        
        # نمایش اولین صفحه پاسخ‌های صحیح
        await show_correct_answers_page(update, context, page=1)
        
        # آنپین کردن پیام تایمر
        if 'timer_message_id' in exam_setup:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id']
                )
            except:
                pass
            
    except Exception as e:
        logger.error(f"Error sending manual finish message: {e}")

# اتمام وارد کردن پاسخ‌های صحیح
async def finish_correct_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if 'exam_setup' not in context.user_data:
        await update.callback_query.message.reply_text("❌ خطا در دریافت اطلاعات آزمون.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') != 'waiting_for_correct_answers_inline':
        await update.callback_query.message.reply_text("❌ مرحله وارد کردن پاسخ‌های صحیح فعال نیست.")
        return
    
    # بررسی اینکه آیا برای همه سوالات پاسخ صحیح وارد شده است
    total_questions = exam_setup.get('total_questions')
    correct_answers_count = len(exam_setup.get('correct_answers', {}))
    
    if correct_answers_count != total_questions:
        await update.callback_query.answer(
            f"❌ لطفاً برای همه {total_questions} سوال پاسخ صحیح وارد کنید. ({correct_answers_count}/{total_questions})",
            show_alert=True
        )
        return
    
    # محاسبه نتایج
    await calculate_results(update, context)

# تغییر به حالت متنی برای وارد کردن پاسخ‌ها
async def switch_to_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if 'exam_setup' not in context.user_data:
        await update.callback_query.message.reply_text("❌ خطا در دریافت اطلاعات آزمون.")
        return
    
    exam_setup = context.user_data['exam_setup']
    exam_setup['step'] = 'waiting_for_correct_answers'
    context.user_data['exam_setup'] = exam_setup
    
    total_questions = exam_setup.get('total_questions')
    
    await update.callback_query.message.reply_text(
        f"🔢 لطفاً پاسخ‌های صحیح را به صورت یک رشته {total_questions} رقمی وارد کنید:\n\n"
        f"مثال: برای ۵ سوال با پاسخ‌های ۱، ۲، ۳، ۴، ۱ وارد کنید:\n"
        f"`12341`"
    )

# تابع اصلی
def main():
    # ایجاد اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # راه‌اندازی دیتابیس
    if not init_db():
        logger.error("Failed to initialize database. Exiting.")
        return
    
    # افزودن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(CallbackQueryHandler(handle_button, pattern="^(new_exam|results|help|start)$"))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # تنظیم منوی دستورات
    application.post_init = set_bot_commands
    
    # تنظیم job برای گزارش روزانه (هر شب ساعت ۲۳:۵۹)
    application.job_queue.run_daily(
        send_daily_report,
        time=datetime.strptime("23:59", "%H:%M").time(),
        days=(0, 1, 2, 3, 4, 5, 6),
        name="daily_report"
    )
    
    # شروع بات
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
