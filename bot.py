import os
import pytesseract
from PIL import Image, ImageEnhance
import psycopg2
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
TOKEN = "7584437136:AAFVtfF9RjCyteONcz8DSg2F2CfhgQT2GcQ"
DATABASE_URL = "postgresql://username:password@localhost:5432/edu_bot_db"
ADMIN_PASSWORD = "admin123"  # رمز عبور ادمین
ADMIN_CODE = "54321"  # کد 5 رقمی ادمین

# حالت های گفتگو
SELECT_SUBJECT, SELECT_GRADE, SELECT_TOPIC, ENTER_QUESTION, ENTER_ANSWER = range(5)
ADMIN_AUTH, ADMIN_ACTION, ADD_SCHEDULE = range(3)
TIMER_SETUP, TIMER_RUNNING = range(2)

# اتصال به پایگاه داده PostgreSQL
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# ایجاد جداول مورد نیاز در صورت عدم وجود
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # جدول کاربران
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(100),
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            is_admin BOOLEAN DEFAULT FALSE,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول سوالات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            subject VARCHAR(50),
            grade VARCHAR(20),
            topic VARCHAR(100),
            question_text TEXT,
            answer_text TEXT,
            image_path VARCHAR(200),
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول برنامه درسی
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            subject VARCHAR(50),
            topic VARCHAR(100),
            due_date TIMESTAMP,
            completed BOOLEAN DEFAULT FALSE,
            added_by_admin BOOLEAN DEFAULT FALSE
        )
    """)
    
    # جدول تایمرها
    cur.execute("""
        CREATE TABLE IF NOT EXISTS timers (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            subject VARCHAR(50),
            duration INTERVAL,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            completed BOOLEAN DEFAULT FALSE
        )
    """)
    
    conn.commit()
    cur.close()
    conn.close()

# ثبت کاربر جدید
def register_user(user_id, username, first_name, last_name):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO users (user_id, username, first_name, last_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id, username, first_name, last_name))
    
    conn.commit()
    cur.close()
    conn.close()

# شروع ربات
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    
    keyboard = [
        [InlineKeyboardButton("📚 اضافه کردن سوال جدید", callback_data='add_question')],
        [InlineKeyboardButton("🔍 جستجوی سوالات", callback_data='search_questions')],
        [InlineKeyboardButton("📅 برنامه درسی", callback_data='study_schedule')],
        [InlineKeyboardButton("⏰ تایمر مطالعه", callback_data='study_timer')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        f"سلام {user.first_name} 👋\n\nبه ربات بانک سوالات درسی خوش آمدید!\n\n"
        "می‌توانید سوالات خود را اضافه کنید، از بانک سوالات جستجو کنید، "
        "برنامه درسی دریافت کنید و از تایمر مطالعه استفاده نمایید.",
        reply_markup=reply_markup
    )

# مدیریت کلیک روی دکمه‌های اینلاین
def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if query.data == 'add_question':
        # نمایش لیست دروس برای انتخاب
        subjects = [
            ["زیست شناسی", "شیمی"],
            ["فیزیک", "ریاضی"],
            ["⏪ بازگشت"]
        ]
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(subject, callback_data=f'subject_{subject}') for subject in row]
            for row in subjects
        ])
        
        query.edit_message_text(
            "لطفاً درس مورد نظر را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return SELECT_SUBJECT
    
    elif query.data == 'search_questions':
        # جستجوی سوالات
        context.bot.send_message(
            chat_id=query.message.chat_id,
            text="لطفاً کلیدواژه جستجو را ارسال کنید:"
        )
        return SEARCH_QUESTIONS
    
    elif query.data == 'study_schedule':
        # نمایش برنامه درسی
        show_schedule_menu(query.message)
    
    elif query.data == 'study_timer':
        # نمایش منوی تایمر
        show_timer_menu(query.message)
    
    elif query.data.startswith('subject_'):
        context.user_data['subject'] = query.data.split('_')[1]
        
        # نمایش پایه‌های تحصیلی
        grades = [
            ["دهم", "یازدهم"],
            ["دوازدهم", "کنکور"],
            ["⏪ بازگشت"]
        ]
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(grade, callback_data=f'grade_{grade}') for grade in row]
            for row in grades
        ])
        
        query.edit_message_text(
            "لطفاً پایه تحصیلی را انتخاب کنید:",
            reply_markup=reply_markup
        )
        return SELECT_GRADE
    
    elif query.data.startswith('grade_'):
        context.user_data['grade'] = query.data.split('_')[1]
        
        query.edit_message_text(
            "لطفاً مبحث درسی را وارد کنید:"
        )
        return SELECT_TOPIC

# پردازش عکس و استخراج متن با Tesseract
def process_image_to_text(image_path):
    try:
        # پیش‌پردازش تصویر
        image = Image.open(image_path).convert('L')  # تبدیل به سیاه و سفید
        image = ImageEnhance.Contrast(image).enhance(2.0)  # افزایش کنتراست
        
        # استخراج متن با Tesseract (پشتیبانی از فارسی)
        custom_config = r'--oem 3 --psm 6 -l fas+eng'
        text = pytesseract.image_to_string(image, config=custom_config)
        
        return text.strip()
    except Exception as e:
        print(f"Error in OCR processing: {e}")
        return None

# ذخیره سوال در پایگاه داده
def save_question_to_db(user_id, subject, grade, topic, question_text, answer_text, image_path=None):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO questions (user_id, subject, grade, topic, question_text, answer_text, image_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, subject, grade, topic, question_text, answer_text, image_path))
    
    conn.commit()
    cur.close()
    conn.close()

# دریافت سوال از کاربر
def receive_question(update: Update, context: CallbackContext) -> int:
    if update.message.photo:
        # اگر کاربر عکس ارسال کرده است
        photo_file = update.message.photo[-1].get_file()
        image_path = f"temp_{update.message.message_id}.jpg"
        photo_file.download(image_path)
        
        # پردازش عکس و استخراج متن
        extracted_text = process_image_to_text(image_path)
        
        if extracted_text:
            context.user_data['question_text'] = extracted_text
            update.message.reply_text(
                f"متن استخراج شده از عکس:\n\n{extracted_text}\n\n"
                "لطفاً پاسخ این سوال را وارد کنید:"
            )
            
            # حذف فایل موقت
            os.remove(image_path)
            return ENTER_ANSWER
        else:
            update.message.reply_text("متأسفانه متن سوال از عکس استخراج نشد. لطفاً متن سوال را به صورت متنی ارسال کنید.")
            return ENTER_QUESTION
    else:
        # اگر کاربر متن ارسال کرده است
        context.user_data['question_text'] = update.message.text
        update.message.reply_text("لطفاً پاسخ این سوال را وارد کنید:")
        return ENTER_ANSWER

# دریافت پاسخ از کاربر
def receive_answer(update: Update, context: CallbackContext) -> int:
    context.user_data['answer_text'] = update.message.text
    
    # ذخیره سوال در پایگاه داده
    save_question_to_db(
        user_id=update.effective_user.id,
        subject=context.user_data['subject'],
        grade=context.user_data['grade'],
        topic=context.user_data['topic'],
        question_text=context.user_data['question_text'],
        answer_text=context.user_data['answer_text']
    )
    
    update.message.reply_text(
        "✅ سوال و پاسخ شما با موفقیت ذخیره شد.\n\n"
        "می‌توانید سوال جدیدی اضافه کنید یا از منوی اصلی استفاده نمایید."
    )
    
    # پاک کردن داده‌های موقت
    context.user_data.clear()
    return ConversationHandler.END

# مدیریت ورود ادمین
def admin_login(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("لطفاً رمز عبور ادمین را وارد کنید:")
    return ADMIN_AUTH

# تأیید اعتبار ادمین
def verify_admin(update: Update, context: CallbackContext) -> int:
    if update.message.text == ADMIN_PASSWORD:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE users SET is_admin = TRUE WHERE user_id = %s
        """, (update.effective_user.id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        update.message.reply_text("✅ شما با موفقیت به عنوان ادمین وارد شدید.")
        show_admin_menu(update.message)
        return ADMIN_ACTION
    else:
        update.message.reply_text("❌ رمز عبور اشتباه است. لطفاً مجدداً تلاش کنید.")
        return ADMIN_AUTH

# نمایش منوی ادمین
def show_admin_menu(message):
    keyboard = [
        [InlineKeyboardButton("➕ اضافه کردن برنامه درسی", callback_data='admin_add_schedule')],
        [InlineKeyboardButton("📊 آمار کاربران", callback_data='admin_stats')],
        [InlineKeyboardButton("📥 خروج از حالت ادمین", callback_data='admin_logout')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message.reply_text(
        "منوی ادمین:\n\nلطفاً عمل مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )

# اضافه کردن برنامه درسی توسط ادمین
def add_schedule_by_admin(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        "لطفاً کد 5 رقمی برنامه درسی را وارد کنید:\n"
        "(این کد برای کاربران نمایش داده خواهد شد)"
    )
    return ADD_SCHEDULE

# ذخیره برنامه درسی در پایگاه داده
def save_schedule_to_db(user_id, subject, topic, due_date, added_by_admin=False):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO schedules (user_id, subject, topic, due_date, added_by_admin)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, subject, topic, due_date, added_by_admin))
    
    conn.commit()
    cur.close()
    conn.close()

# نمایش برنامه درسی
def show_schedule_menu(message):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT subject, topic, due_date, completed, id
        FROM schedules
        WHERE user_id = %s
        ORDER BY due_date
    """, (message.chat_id,))
    
    schedules = cur.fetchall()
    cur.close()
    conn.close()
    
    if not schedules:
        message.reply_text("هنوز برنامه درسی برای شما تنظیم نشده است.")
        return
    
    text = "📅 برنامه درسی شما:\n\n"
    keyboard = []
    
    for subject, topic, due_date, completed, schedule_id in schedules:
        status = "✅" if completed else "🕒"
        text += f"{status} {subject} - {topic} (تا {due_date.strftime('%Y-%m-%d')})\n"
        
        if not completed:
            keyboard.append([InlineKeyboardButton(
                f"تکمیل: {subject} - {topic}",
                callback_data=f"complete_{schedule_id}"
            )])
    
    keyboard.append([InlineKeyboardButton("➕ اضافه کردن برنامه جدید", callback_data='add_schedule')])
    keyboard.append([InlineKeyboardButton("⏪ بازگشت", callback_data='back_to_main')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message.reply_text(text, reply_markup=reply_markup)

# نمایش منوی تایمر
def show_timer_menu(message):
    keyboard = [
        [InlineKeyboardButton("⏳ شروع تایمر جدید", callback_data='start_timer')],
        [InlineKeyboardButton("📊 گزارش تایمرها", callback_data='timer_reports')],
        [InlineKeyboardButton("⏪ بازگشت", callback_data='back_to_main')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message.reply_text(
        "⏰ منوی تایمر مطالعه:\n\nلطفاً عمل مورد نظر را انتخاب کنید:",
        reply_markup=reply_markup
    )

# شروع تایمر مطالعه
def start_timer(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    subjects = [
        ["زیست شناسی", "شیمی"],
        ["فیزیک", "ریاضی"],
        ["⏪ بازگشت"]
    ]
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(subject, callback_data=f'timer_subject_{subject}') for subject in row]
        for row in subjects
    ])
    
    query.edit_message_text(
        "لطفاً درس مورد نظر برای تایمر را انتخاب کنید:",
        reply_markup=reply_markup
    )
    return TIMER_SETUP

# تنظیم مدت زمان تایمر
def set_timer_duration(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    subject = query.data.split('_')[-1]
    context.user_data['timer_subject'] = subject
    
    durations = [
        ["25 دقیقه", "45 دقیقه"],
        ["1 ساعت", "1.5 ساعت"],
        ["2 ساعت", "⏪ بازگشت"]
    ]
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(dur, callback_data=f'timer_dur_{dur}') for dur in row]
        for row in durations
    ])
    
    query.edit_message_text(
        f"⏳ تایمر مطالعه {subject}\n\nلطفاً مدت زمان را انتخاب کنید:",
        reply_markup=reply_markup
    )

# شروع تایمر
def run_timer(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    duration_str = query.data.split('_')[-1]
    
    # تبدیل مدت زمان به timedelta
    if 'دقیقه' in duration_str:
        minutes = float(duration_str.split()[0])
        duration = timedelta(minutes=minutes)
    elif 'ساعت' in duration_str:
        hours = float(duration_str.split()[0])
        duration = timedelta(hours=hours)
    
    start_time = datetime.now()
    end_time = start_time + duration
    
    # ذخیره تایمر در پایگاه داده
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO timers (user_id, subject, duration, start_time, end_time)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        query.message.chat_id,
        context.user_data['timer_subject'],
        duration,
        start_time,
        end_time
    ))
    
    conn.commit()
    cur.close()
    conn.close()
    
    # نمایش تایمر در حال اجرا
    remaining = end_time - datetime.now()
    remaining_min = int(remaining.total_seconds() / 60)
    
    keyboard = [
        [InlineKeyboardButton("⏹ توقف تایمر", callback_data=f'stop_timer')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = query.edit_message_text(
        f"⏳ تایمر مطالعه {context.user_data['timer_subject']} فعال شد!\n\n"
        f"زمان باقیمانده: {remaining_min} دقیقه",
        reply_markup=reply_markup
    )
    
    # به‌روزرسانی تایمر هر دقیقه
    context.job_queue.run_repeating(
        update_timer,
        interval=60,
        first=0,
        context={
            'chat_id': query.message.chat_id,
            'message_id': message.message_id,
            'end_time': end_time,
            'subject': context.user_data['timer_subject']
        }
    )
    
    context.user_data['timer_job'] = {
        'chat_id': query.message.chat_id,
        'message_id': message.message_id,
        'job': context.job_queue.jobs()[-1]
    }
    
    return TIMER_RUNNING

# به‌روزرسانی تایمر
def update_timer(context: CallbackContext):
    job = context.job
    remaining = job.context['end_time'] - datetime.now()
    
    if remaining.total_seconds() <= 0:
        # تایمر به پایان رسیده است
        context.bot.edit_message_text(
            chat_id=job.context['chat_id'],
            message_id=job.context['message_id'],
            text=f"⏰ تایمر مطالعه {job.context['subject']} به پایان رسید! 🎉"
        )
        
        # به‌روزرسانی وضعیت در پایگاه داده
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE timers
            SET completed = TRUE
            WHERE user_id = %s AND end_time = %s
        """, (job.context['chat_id'], job.context['end_time']))
        
        conn.commit()
        cur.close()
        conn.close()
        
        job.schedule_removal()
    else:
        remaining_min = int(remaining.total_seconds() / 60)
        
        keyboard = [
            [InlineKeyboardButton("⏹ توقف تایمر", callback_data=f'stop_timer')]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        context.bot.edit_message_text(
            chat_id=job.context['chat_id'],
            message_id=job.context['message_id'],
            text=f"⏳ تایمر مطالعه {job.context['subject']} در حال اجراست!\n\n"
                 f"زمان باقیمانده: {remaining_min} دقیقه",
            reply_markup=reply_markup
        )

# توقف تایمر
def stop_timer(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if 'timer_job' in context.user_data:
        job = context.user_data['timer_job']['job']
        job.schedule_removal()
        
        # به‌روزرسانی وضعیت در پایگاه داده
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE timers
            SET completed = TRUE, end_time = %s
            WHERE user_id = %s AND completed = FALSE
        """, (datetime.now(), query.message.chat_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        query.edit_message_text("⏹ تایمر مطالعه متوقف شد.")
    else:
        query.edit_message_text("⚠️ تایمر فعالی برای توقف وجود ندارد.")
    
    return ConversationHandler.END

# گزارش تایمرها
def show_timer_reports(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT subject, SUM(duration), COUNT(*)
        FROM timers
        WHERE user_id = %s AND completed = TRUE
        GROUP BY subject
    """, (query.message.chat_id,))
    
    reports = cur.fetchall()
    cur.close()
    conn.close()
    
    if not reports:
        query.edit_message_text("هنوز گزارشی از تایمرهای شما وجود ندارد.")
        return
    
    text = "📊 گزارش مطالعه شما:\n\n"
    total_hours = 0
    
    for subject, total_duration, count in reports:
        hours = total_duration.total_seconds() / 3600
        total_hours += hours
        text += f"📚 {subject}: {count} جلسه - {hours:.1f} ساعت\n"
    
    text += f"\n✅ مجموع ساعت‌های مطالعه: {total_hours:.1f} ساعت"
    
    keyboard = [
        [InlineKeyboardButton("⏪ بازگشت", callback_data='back_to_timer')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text, reply_markup=reply_markup)

# تایید تکمیل برنامه درسی
def complete_schedule(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    schedule_id = int(query.data.split('_')[1])
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE schedules
        SET completed = TRUE
        WHERE id = %s
    """, (schedule_id,))
    
    conn.commit()
    cur.close()
    conn.close()
    
    query.edit_message_text("✅ برنامه درسی با موفقیت به عنوان تکمیل شده علامت زده شد.")
    show_schedule_menu(query.message)

# تابع اصلی
def main():
    # راه‌اندازی پایگاه داده
    init_db()
    
    # ایجاد آپدیت و دیسپچر
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    
    # تعریف هندلرهای گفتگو
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern='^add_question$'),
            CommandHandler('admin', admin_login)
        ],
        states={
            SELECT_SUBJECT: [CallbackQueryHandler(button_handler, pattern='^subject_')],
            SELECT_GRADE: [CallbackQueryHandler(button_handler, pattern='^grade_')],
            SELECT_TOPIC: [MessageHandler(Filters.text & ~Filters.command, lambda u, c: receive_question(u, c))],
            ENTER_QUESTION: [MessageHandler(Filters.text | Filters.photo, receive_question)],
            ENTER_ANSWER: [MessageHandler(Filters.text & ~Filters.command, receive_answer)],
            ADMIN_AUTH: [MessageHandler(Filters.text & ~Filters.command, verify_admin)],
            ADMIN_ACTION: [CallbackQueryHandler(button_handler, pattern='^admin_')],
            ADD_SCHEDULE: [MessageHandler(Filters.text & ~Filters.command, add_schedule)],
            TIMER_SETUP: [CallbackQueryHandler(set_timer_duration, pattern='^timer_subject_')],
            TIMER_RUNNING: [CallbackQueryHandler(stop_timer, pattern='^stop_timer$')]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)],
    )
    
    # ثبت هندلرها
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(CallbackQueryHandler(show_timer_reports, pattern='^timer_reports$'))
    dispatcher.add_handler(CallbackQueryHandler(complete_schedule, pattern='^complete_'))
    dispatcher.add_handler(CallbackQueryHandler(start_timer, pattern='^start_timer$'))
    dispatcher.add_handler(CallbackQueryHandler(set_timer_duration, pattern='^timer_dur_'))
    dispatcher.add_handler(CallbackQueryHandler(run_timer, pattern='^timer_dur_'))
    
    # شروع ربات
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
