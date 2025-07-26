import os
import pytesseract
from PIL import Image, ImageEnhance
from io import BytesIO
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
)

# تنظیمات اولیه
TOKEN = '7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ'
DATABASE_URL = 'postgresql://user:password@localhost:5432/school_bot'
ADMIN_PASSWORD = 'admin123'
USER_CODE_LENGTH = 5

# حالتهای گفتگو
SELECTING_ACTION, ADDING_QUESTION, ADDING_SCHEDULE, VIEWING_REPORT = range(4)
SUBJECT, GRADE, TOPIC, QUESTION_TEXT, ANSWER = range(5)
SCHEDULE_SUBJECT, SCHEDULE_TOPIC, SCHEDULE_TIME, SCHEDULE_DURATION = range(4)
TIMER_SETUP, TIMER_RUNNING = range(2)

# اتصال به پایگاه داده
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # ایجاد جدول کاربران
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username VARCHAR(100),
        first_name VARCHAR(100),
        last_name VARCHAR(100),
        access_code VARCHAR(10),
        is_admin BOOLEAN DEFAULT FALSE
    )
    """)
    
    # ایجاد جدول سوالات
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        subject VARCHAR(50),
        grade VARCHAR(20),
        topic VARCHAR(100),
        question_text TEXT,
        answer TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)
    
    # ایجاد جدول برنامه درسی
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        subject VARCHAR(50),
        topic VARCHAR(100),
        schedule_time TIMESTAMP,
        duration_minutes INTEGER,
        is_completed BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    )
    """)
    
    # ایجاد جدول تایمرها
    cur.execute("""
    CREATE TABLE IF NOT EXISTS timers (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        start_time TIMESTAMP,
        duration_minutes INTEGER,
        is_active BOOLEAN DEFAULT TRUE,
        task_description TEXT
    )
    """)
    
    conn.commit()
    cur.close()
    conn.close()

# توابع کمکی
def extract_text_from_image(image_file):
    try:
        image = Image.open(BytesIO(image_file))
        image = image.convert('L')  # تبدیل به سیاه و سفید
        image = ImageEnhance.Contrast(image).enhance(2.0)  # افزایش کنتراست
        
        # تنظیمات Tesseract برای فارسی
        custom_config = r'--oem 3 --psm 6 -l fas+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
        return text.strip()
    except Exception as e:
        print(f"Error in OCR: {e}")
        return None

def generate_access_code():
    import random
    return ''.join(random.choices('0123456789', k=USER_CODE_LENGTH))

# دستورات کاربران
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    conn = get_db_connection()
    cur = conn.cursor()
    
    # بررسی وجود کاربر در دیتابیس
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user.id,))
    if not cur.fetchone():
        access_code = generate_access_code()
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, access_code) VALUES (%s, %s, %s, %s, %s)",
            (user.id, user.username, user.first_name, user.last_name, access_code)
        )
        conn.commit()
        update.message.reply_text(
            f"سلام {user.first_name}!\n"
            f"کد دسترسی شخصی شما: {access_code}\n"
            "از این کد برای ورود به برنامه‌های دیگر استفاده کنید."
        )
    else:
        update.message.reply_text(f"سلام {user.first_name}!\nخوش آمدید!")
    
    show_main_menu(update, context)
    cur.close()
    conn.close()
    return SELECTING_ACTION

def show_main_menu(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("اضافه کردن سوال جدید", callback_data='add_question')],
        [InlineKeyboardButton("مشاهده بانک سوالات", callback_data='view_questions')],
        [InlineKeyboardButton("برنامه درسی", callback_data='study_schedule')],
        [InlineKeyboardButton("تایمر مطالعه", callback_data='study_timer')],
        [InlineKeyboardButton("گزارش کار", callback_data='view_report')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            text="منوی اصلی:",
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            text="منوی اصلی:",
            reply_markup=reply_markup
        )

# مدیریت سوالات
def add_question(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="لطفا درس مربوطه را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("زیست شناسی", callback_data='subject_biology')],
            [InlineKeyboardButton("شیمی", callback_data='subject_chemistry')],
            [InlineKeyboardButton("فیزیک", callback_data='subject_physics')],
            [InlineKeyboardButton("ریاضی", callback_data='subject_math')],
            [InlineKeyboardButton("بازگشت", callback_data='back_to_main')]
        ])
    )
    return SUBJECT

def subject_selected(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    subject_map = {
        'subject_biology': 'زیست شناسی',
        'subject_chemistry': 'شیمی',
        'subject_physics': 'فیزیک',
        'subject_math': 'ریاضی'
    }
    
    if query.data == 'back_to_main':
        show_main_menu(update, context)
        return SELECTING_ACTION
    
    context.user_data['subject'] = subject_map[query.data]
    
    query.edit_message_text(
        text="پایه تحصیلی را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("دهم", callback_data='grade_10')],
            [InlineKeyboardButton("یازدهم", callback_data='grade_11')],
            [InlineKeyboardButton("دوازدهم", callback_data='grade_12')],
            [InlineKeyboardButton("بازگشت", callback_data='back_to_subject')]
        ])
    )
    return GRADE

def grade_selected(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data == 'back_to_subject':
        return add_question(update, context)
    
    context.user_data['grade'] = query.data.split('_')[1]
    
    query.edit_message_text(text="لطفا مبحث درسی را وارد کنید:")
    return TOPIC

def topic_entered(update: Update, context: CallbackContext):
    context.user_data['topic'] = update.message.text
    
    update.message.reply_text(
        "لطفا سوال را وارد کنید یا عکس آن را ارسال کنید:\n"
        "می‌توانید از /skip رد شوید."
    )
    return QUESTION_TEXT

def question_text_received(update: Update, context: CallbackContext):
    if update.message.text and update.message.text.lower() == '/skip':
        context.user_data['question_text'] = None
    elif update.message.text:
        context.user_data['question_text'] = update.message.text
    elif update.message.photo:
        photo_file = update.message.photo[-1].get_file()
        image_bytes = BytesIO()
        photo_file.download(out=image_bytes)
        extracted_text = extract_text_from_image(image_bytes.getvalue())
        if extracted_text:
            context.user_data['question_text'] = extracted_text
        else:
            update.message.reply_text("متاسفانه متن سوال قابل استخراج نبود. لطفا متن سوال را تایپ کنید.")
            return QUESTION_TEXT
    
    update.message.reply_text(
        "لطفا پاسخ سوال را وارد کنید یا عکس آن را ارسال کنید:\n"
        "می‌توانید از /skip رد شوید."
    )
    return ANSWER

def answer_received(update: Update, context: CallbackContext):
    if update.message.text and update.message.text.lower() == '/skip':
        context.user_data['answer'] = None
    elif update.message.text:
        context.user_data['answer'] = update.message.text
    elif update.message.photo:
        photo_file = update.message.photo[-1].get_file()
        image_bytes = BytesIO()
        photo_file.download(out=image_bytes)
        extracted_text = extract_text_from_image(image_bytes.getvalue())
        if extracted_text:
            context.user_data['answer'] = extracted_text
        else:
            update.message.reply_text("متاسفانه متن پاسخ قابل استخراج نبود. لطفا متن پاسخ را تایپ کنید.")
            return ANSWER
    
    # ذخیره سوال در دیتابیس
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute(
        "INSERT INTO questions (user_id, subject, grade, topic, question_text, answer) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            update.effective_user.id,
            context.user_data['subject'],
            context.user_data['grade'],
            context.user_data['topic'],
            context.user_data.get('question_text'),
            context.user_data.get('answer')
        )
    )
    conn.commit()
    
    update.message.reply_text("سوال با موفقیت به بانک سوالات اضافه شد!")
    
    show_main_menu(update, context)
    cur.close()
    conn.close()
    return SELECTING_ACTION

# مدیریت برنامه درسی
def study_schedule(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    keyboard = [
        [InlineKeyboardButton("اضافه کردن برنامه جدید", callback_data='add_schedule')],
        [InlineKeyboardButton("مشاهده برنامه‌ها", callback_data='view_schedules')],
        [InlineKeyboardButton("برنامه‌های تکمیل شده", callback_data='completed_schedules')],
        [InlineKeyboardButton("بازگشت", callback_data='back_to_main')]
    ]
    
    query.edit_message_text(
        text="مدیریت برنامه درسی:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADDING_SCHEDULE

def add_schedule(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="لطفا درس مربوطه را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("زیست شناسی", callback_data='schedule_biology')],
            [InlineKeyboardButton("شیمی", callback_data='schedule_chemistry')],
            [InlineKeyboardButton("فیزیک", callback_data='schedule_physics')],
            [InlineKeyboardButton("ریاضی", callback_data='schedule_math')],
            [InlineKeyboardButton("بازگشت", callback_data='back_to_schedule')]
        ])
    )
    return SCHEDULE_SUBJECT

def schedule_subject_selected(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    subject_map = {
        'schedule_biology': 'زیست شناسی',
        'schedule_chemistry': 'شیمی',
        'schedule_physics': 'فیزیک',
        'schedule_math': 'ریاضی'
    }
    
    if query.data == 'back_to_schedule':
        return study_schedule(update, context)
    
    context.user_data['schedule_subject'] = subject_map[query.data]
    
    query.edit_message_text(text="لطفا مبحث درسی را وارد کنید:")
    return SCHEDULE_TOPIC

def schedule_topic_entered(update: Update, context: CallbackContext):
    context.user_data['schedule_topic'] = update.message.text
    
    update.message.reply_text(
        "لطفا زمان برنامه را به فرمت زیر وارد کنید:\n"
        "مثال: 1403-05-15 16:30"
    )
    return SCHEDULE_TIME

def schedule_time_entered(update: Update, context: CallbackContext):
    try:
        schedule_time = datetime.strptime(update.message.text, '%Y-%m-%d %H:%M')
        context.user_data['schedule_time'] = schedule_time
        
        update.message.reply_text(
            "لطفا مدت زمان مطالعه (به دقیقه) را وارد کنید:"
        )
        return SCHEDULE_DURATION
    except ValueError:
        update.message.reply_text(
            "فرمت زمان نادرست است. لطفا به فرمت مثال وارد کنید:\n"
            "1403-05-15 16:30"
        )
        return SCHEDULE_TIME

def schedule_duration_entered(update: Update, context: CallbackContext):
    try:
        duration = int(update.message.text)
        
        # ذخیره برنامه در دیتابیس
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO schedules (user_id, subject, topic, schedule_time, duration_minutes) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                update.effective_user.id,
                context.user_data['schedule_subject'],
                context.user_data['schedule_topic'],
                context.user_data['schedule_time'],
                duration
            )
        )
        conn.commit()
        
        update.message.reply_text("برنامه درسی با موفقیت اضافه شد!")
        
        show_main_menu(update, context)
        cur.close()
        conn.close()
        return SELECTING_ACTION
    except ValueError:
        update.message.reply_text("لطفا یک عدد صحیح وارد کنید (مدت زمان به دقیقه):")
        return SCHEDULE_DURATION

# مدیریت تایمر مطالعه
def study_timer(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    keyboard = [
        [InlineKeyboardButton("شروع تایمر جدید", callback_data='start_timer')],
        [InlineKeyboardButton("مشاهده تایمرهای فعال", callback_data='view_active_timers')],
        [InlineKeyboardButton("بازگشت", callback_data='back_to_main')]
    ]
    
    query.edit_message_text(
        text="مدیریت تایمر مطالعه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return TIMER_SETUP

def start_timer(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="لطفا مدت زمان مطالعه (به دقیقه) را وارد کنید:"
    )
    return TIMER_RUNNING

def timer_duration_entered(update: Update, context: CallbackContext):
    try:
        duration = int(update.message.text)
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration)
        
        # ذخیره تایمر در دیتابیس
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute(
            "INSERT INTO timers (user_id, start_time, duration_minutes, task_description) "
            "VALUES (%s, %s, %s, %s)",
            (
                update.effective_user.id,
                start_time,
                duration,
                "زمان مطالعه"
            )
        )
        conn.commit()
        
        # ایجاد یک job برای اعلان پایان تایمر
        context.job_queue.run_once(
            timer_completed,
            duration * 60,
            context=update.effective_user.id,
            name=str(update.effective_user.id)
        )
        
        update.message.reply_text(
            f"تایمر مطالعه برای {duration} دقیقه شروع شد!\n"
            f"پایان تایمر: {end_time.strftime('%H:%M')}"
        )
        
        show_main_menu(update, context)
        cur.close()
        conn.close()
        return SELECTING_ACTION
    except ValueError:
        update.message.reply_text("لطفا یک عدد صحیح وارد کنید (مدت زمان به دقیقه):")
        return TIMER_RUNNING

def timer_completed(context: CallbackContext):
    job = context.job
    user_id = job.context
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute(
        "UPDATE timers SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE",
        (user_id,)
    )
    conn.commit()
    
    context.bot.send_message(
        chat_id=user_id,
        text="⏰ تایمر مطالعه شما به پایان رسید! خوب کار کردید!"
    )
    
    cur.close()
    conn.close()

# مدیریت گزارشات
def view_report(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    
    # تعداد سوالات اضافه شده
    cur.execute(
        "SELECT COUNT(*) FROM questions WHERE user_id = %s",
        (user_id,)
    )
    questions_count = cur.fetchone()[0]
    
    # تعداد برنامه‌های تکمیل شده
    cur.execute(
        "SELECT COUNT(*) FROM schedules WHERE user_id = %s AND is_completed = TRUE",
        (user_id,)
    )
    completed_schedules = cur.fetchone()[0]
    
    # مجموع زمان مطالعه
    cur.execute(
        "SELECT SUM(duration_minutes) FROM timers WHERE user_id = %s",
        (user_id,)
    )
    total_study_time = cur.fetchone()[0] or 0
    
    report_text = (
        f"📊 گزارش عملکرد تحصیلی:\n\n"
        f"📝 تعداد سوالات اضافه شده: {questions_count}\n"
        f"✅ برنامه‌های تکمیل شده: {completed_schedules}\n"
        f"⏳ مجموع زمان مطالعه: {total_study_time} دقیقه\n\n"
        f"آفرین! به خوبی ادامه دهید!"
    )
    
    query.edit_message_text(
        text=report_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت", callback_data='back_to_main')]
        ])
    )
    
    cur.close()
    conn.close()
    return VIEWING_REPORT

# مدیریت ادمین
def admin_panel(update: Update, context: CallbackContext):
    if update.message.text.split()[-1] != ADMIN_PASSWORD:
        update.message.reply_text("دسترسی رد شد!")
        return
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # دریافت تمام کدهای دسترسی کاربران
    cur.execute(
        "SELECT user_id, first_name, last_name, access_code FROM users WHERE is_admin = FALSE"
    )
    users = cur.fetchall()
    
    report_text = "👥 لیست کاربران و کدهای دسترسی:\n\n"
    for user in users:
        report_text += f"{user[1]} {user[2]}: {user[3]}\n"
    
    update.message.reply_text(report_text)
    
    cur.close()
    conn.close()

# تابع اصلی
def main():
    # تنظیم مسیر Tesseract اگر به PATH اضافه نشده
    pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'  # برای لینوکس
    
    # مقداردهی اولیه دیتابیس
    init_db()
    
    # ایجاد آپدیت و دیسپچر
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    
    # تعریف handlerهای گفتگو
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(add_question, pattern='^add_question$'),
                CallbackQueryHandler(study_schedule, pattern='^study_schedule$'),
                CallbackQueryHandler(study_timer, pattern='^study_timer$'),
                CallbackQueryHandler(view_report, pattern='^view_report$'),
                CallbackQueryHandler(show_main_menu, pattern='^back_to_main$')
            ],
            SUBJECT: [
                CallbackQueryHandler(subject_selected),
                CallbackQueryHandler(show_main_menu, pattern='^back_to_main$')
            ],
            GRADE: [
                CallbackQueryHandler(grade_selected),
                CallbackQueryHandler(add_question, pattern='^back_to_subject$')
            ],
            TOPIC: [MessageHandler(Filters.text & ~Filters.command, topic_entered)],
            QUESTION_TEXT: [
                MessageHandler(Filters.text & ~Filters.command, question_text_received),
                MessageHandler(Filters.photo, question_text_received),
                CommandHandler('skip', question_text_received)
            ],
            ANSWER: [
                MessageHandler(Filters.text & ~Filters.command, answer_received),
                MessageHandler(Filters.photo, answer_received),
                CommandHandler('skip', answer_received)
            ],
            ADDING_SCHEDULE: [
                CallbackQueryHandler(add_schedule, pattern='^add_schedule$'),
                CallbackQueryHandler(show_main_menu, pattern='^back_to_main$')
            ],
            SCHEDULE_SUBJECT: [
                CallbackQueryHandler(schedule_subject_selected),
                CallbackQueryHandler(study_schedule, pattern='^back_to_schedule$')
            ],
            SCHEDULE_TOPIC: [MessageHandler(Filters.text & ~Filters.command, schedule_topic_entered)],
            SCHEDULE_TIME: [MessageHandler(Filters.text & ~Filters.command, schedule_time_entered)],
            SCHEDULE_DURATION: [MessageHandler(Filters.text & ~Filters.command, schedule_duration_entered)],
            TIMER_SETUP: [
                CallbackQueryHandler(start_timer, pattern='^start_timer$'),
                CallbackQueryHandler(show_main_menu, pattern='^back_to_main$')
            ],
            TIMER_RUNNING: [MessageHandler(Filters.text & ~Filters.command, timer_duration_entered)],
            VIEWING_REPORT: [
                CallbackQueryHandler(show_main_menu, pattern='^back_to_main$')
            ]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(CommandHandler('admin', admin_panel))
    
    # شروع ربات
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
