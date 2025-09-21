import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# مدیریت دستور start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome_text = "🎯 Let's create answer sheets and compete!\n\nUse the /new_exam command to get started."
    await update.message.reply_text(welcome_text)

# ایجاد آزمون جدید
async def new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # پاک کردن وضعیت قبلی
    context.user_data.pop('exam_setup', None)
    
    # ایجاد وضعیت جدید
    context.user_data['exam_setup'] = {'step': 'course_name'}
    
    await update.message.reply_text(
        "📚 Please enter the course name:"
    )

# نمایش تمام سوالات به صورت همزمان با فرمت جدید
async def show_all_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam_setup = context.user_data['exam_setup']
    start_question = exam_setup.get('start_question')
    end_question = exam_setup.get('end_question')
    user_answers = exam_setup.get('answers', {})
    
    course_name = exam_setup.get('course_name', 'Unknown')
    topic_name = exam_setup.get('topic_name', 'Unknown')
    
    message_text = f"📚 Course: {course_name}\n"
    message_text += f"📖 Topic: {topic_name}\n\n"
    message_text += "📝 Please answer the questions:\n\n"
    
    # ایجاد دکمه‌های اینلاین برای تمام سوالات
    keyboard = []
    
    for question_num in range(start_question, end_question + 1):
        # وضعیت پاسخ فعلی
        current_answer = user_answers.get(str(question_num))
        status = f" ✅ (Option {current_answer})" if current_answer else ""
        
        # اضافه کردن سوال به متن پیام
        # message_text += f"{question_num}){status}\n"
        
        # ایجاد دکمه‌های گزینه‌ها برای هر سوال با شماره سوال
        question_buttons = []
        # دکمه شماره سوال (غیرفعال)
        question_buttons.append(InlineKeyboardButton(f"{question_num}", callback_data="ignore"))
        
        for option in [1, 2, 3, 4]:
            # اگر این گزینه قبلاً انتخاب شده، علامت ✅ نشان داده شود
            button_text = f"{option} ✅" if current_answer == option else str(option)
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    # اضافه کردن دکمه اتمام آزمون (فارسی)
    keyboard.append([InlineKeyboardButton("🎯 اتمام آزمون و ارسال پاسخ‌ها", callback_data="finish_exam")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
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
    
    course_name = exam_setup.get('course_name', 'Unknown')
    topic_name = exam_setup.get('topic_name', 'Unknown')
    
    # فقط نوار پیشرفت و زمان باقیمانده نمایش داده شود
    timer_text = f"📚 {course_name} - {topic_name}\n⏳ Remaining: {minutes:02d}:{seconds:02d}\n{progress_bar}"
    
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
    exam_setup['step'] = 'waiting_for_correct_answers'
    context.bot_data['user_exams'][user_id] = exam_setup
    
    # حذف job تایمر
    job_name = f"timer_{user_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    
    total_questions = exam_setup.get('total_questions')
    answered_count = len(exam_setup.get('answers', {}))
    
    course_name = exam_setup.get('course_name', 'Unknown')
    topic_name = exam_setup.get('topic_name', 'Unknown')
    
    # ارسال پیام اتمام زمان
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📚 {course_name} - {topic_name}\n"
                 f"⏰ Exam time is over!\n"
                 f"📊 You answered {answered_count} out of {total_questions} questions.\n\n"
                 f"Please send the correct answers as a {total_questions}-digit string without spaces.\n\n"
                 f"📋 Example: for {total_questions} questions: {'1' * total_questions}"
        )
        
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
        await update.message.reply_text("Please start a new exam first with the /new_exam command.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') == 'course_name':
        if not text:
            await update.message.reply_text("❌ Course name cannot be empty. Please enter again:")
            return
            
        exam_setup['course_name'] = text
        exam_setup['step'] = 'topic_name'
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text(
            "📖 Please enter the topic name:"
        )
    
    elif exam_setup.get('step') == 'topic_name':
        if not text:
            await update.message.reply_text("❌ Topic name cannot be empty. Please enter again:")
            return
            
        exam_setup['topic_name'] = text
        exam_setup['step'] = 1
        context.user_data['exam_setup'] = exam_setup
        await update.message.reply_text(
            "🔢 Please enter the first question number:"
        )
    
    elif exam_setup.get('step') == 1:
        try:
            start_question = int(text)
            if start_question <= 0:
                await update.message.reply_text("❌ Question number must be greater than zero.")
                return
                
            exam_setup['start_question'] = start_question
            exam_setup['step'] = 2
            context.user_data['exam_setup'] = exam_setup
            await update.message.reply_text(
                "🔢 Please enter the last question number:"
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
    
    elif exam_setup.get('step') == 2:
        try:
            end_question = int(text)
            start_question = exam_setup.get('start_question')
            
            if end_question <= start_question:
                await update.message.reply_text("❌ Last question number must be greater than first question.")
                return
            
            total_questions = end_question - start_question + 1
            if total_questions > 50:
                await update.message.reply_text("❌ Maximum allowed number of questions is 50.")
                return
                
            exam_setup['end_question'] = end_question
            exam_setup['total_questions'] = total_questions
            exam_setup['step'] = 3
            context.user_data['exam_setup'] = exam_setup
            
            await update.message.reply_text(
                "⏰ Please enter the exam duration in minutes (0 for no time limit):"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
    
    elif exam_setup.get('step') == 3:
        try:
            exam_duration = int(text)
            if exam_duration < 0:
                await update.message.reply_text("❌ Exam time cannot be negative.")
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
            
            # نمایش تمام سوالات به صورت همزمان
            await show_all_questions(update, context)
            
            # نمایش تایمر پین شده
            await show_pinned_timer(context, user_id, exam_setup)
            
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number.")
    
    elif exam_setup.get('step') == 'waiting_for_correct_answers':
        total_questions = exam_setup.get('total_questions')
        
        # حذف فاصله و کاراکترهای غیرعددی
        cleaned_text = ''.join(filter(str.isdigit, text))
        
        if len(cleaned_text) != total_questions:
            await update.message.reply_text(
                f"❌ The sent string must contain {total_questions} digits. You entered {len(cleaned_text)} digits. Please enter again:"
            )
            return
        
        correct_answers = [int(char) for char in cleaned_text]
        user_answers = exam_setup.get('answers', {})
        correct_questions = []
        wrong_questions = []
        unanswered_questions = []
        
        start_q = exam_setup.get('start_question')
        end_q = exam_setup.get('end_question')
        
        for i in range(start_q, end_q + 1):
            user_answer = user_answers.get(str(i))
            correct_answer = correct_answers[i - start_q]
            
            if user_answer is None:
                unanswered_questions.append(i)
            elif user_answer == correct_answer:
                correct_questions.append(i)
            else:
                wrong_questions.append(i)
        
        # محاسبه نتایج
        correct_count = len(correct_questions)
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)

        # درصد بدون نمره منفی
        percentage_without_penalty = (correct_count / total_questions) * 100 if total_questions > 0 else 0

        # محاسبه نمره منفی
        raw_score = correct_count
        penalty = wrong_count / 3.0  # کسر ⅓ نمره به ازای هر پاسخ اشتباه
        final_score = max(0, raw_score - penalty)
        final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0

        # محاسبه زمان صرف شده
        elapsed_time = calculate_elapsed_time(exam_setup.get('start_time'))
        
        # دریافت تاریخ و زمان تهران
        jalali_date = get_jalali_date()
        tehran_time = get_tehran_time()
        
        # ذخیره نتایج در دیتابیس
        saved_to_db = False
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                
                cur.execute(
                    """
                    INSERT INTO exams 
                    (user_id, course_name, topic_name, start_question, end_question, total_questions, 
                     exam_duration, elapsed_time, answers, correct_answers, score, wrong_questions, 
                     unanswered_questions, jalali_date, tehran_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        exam_setup.get('course_name'),
                        exam_setup.get('topic_name'),
                        exam_setup.get('start_question'),
                        exam_setup.get('end_question'),
                        total_questions,
                        exam_setup.get('exam_duration'),
                        elapsed_time,
                        str(user_answers),
                        cleaned_text,
                        final_percentage,
                        str(wrong_questions),
                        str(unanswered_questions),
                        jalali_date,
                        tehran_time
                    )
                )
                conn.commit()
                cur.close()
                conn.close()
                saved_to_db = True
        except Exception as e:
            logger.error(f"Error saving to database: {e}")

        course_name = exam_setup.get('course_name', 'Unknown')
        topic_name = exam_setup.get('topic_name', 'Unknown')
        
        # ارسال نتایج
        result_text = f"""
📊 Your exam results:

📚 Course: {course_name}
📖 Topic: {topic_name}
📅 Date: {jalali_date}
⏰ Time: {tehran_time}

✅ Correct answers: {correct_count}
❌ Wrong answers: {wrong_count}
⏸️ Unanswered: {unanswered_count}
📝 Total questions: {total_questions}
⏰ Time spent: {elapsed_time:.2f} minutes

📈 Score without penalty: {percentage_without_penalty:.2f}%
📉 Score with penalty: {final_percentage:.2f}%

🔢 Correct questions: {', '.join(map(str, correct_questions)) if correct_questions else 'None'}
🔢 Wrong questions: {', '.join(map(str, wrong_questions)) if wrong_questions else 'None'}
🔢 Unanswered questions: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'None'}

💡 Note: Every 3 wrong answers equals 1 correct answer penalty.
"""

        if not saved_to_db:
            result_text += "\n\n⚠️ Results were not saved to database (connection issue)."

        await update.message.reply_text(result_text)
        
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
        
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()

# مدیریت پاسخ‌های اینلاین
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "ignore":
        return
    
    if 'exam_setup' not in context.user_data:
        await query.edit_message_text("⚠️ Please start a new exam first with /new_exam.")
        return
        
    exam_setup = context.user_data['exam_setup']
    
    if data.startswith("ans_"):
        parts = data.split("_")
        question_num = int(parts[1])
        answer = int(parts[2])
        
        exam_setup['answers'][str(question_num)] = answer
        context.user_data['exam_setup'] = exam_setup
        
        # به روزرسانی در bot_data نیز
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        # به جای حذف پیام، آن را ویرایش کنیم
        try:
            await show_all_questions(update, context)
        except Exception as e:
            logger.error(f"Error updating message: {e}")
            # اگر ویرایش ناموفق بود، پیام جدید ارسال نکنیم
    
    elif data == "finish_exam":
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
        # محاسبه زمان صرف شده
        start_time = exam_setup.get('start_time')
        elapsed_time = calculate_elapsed_time(start_time)
        exam_setup['elapsed_time'] = elapsed_time
        
        # به روزرسانی در bot_data نیز
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        # حذف تایمر
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        # آنپین کردن پیام تایمر
        if 'timer_message_id' in exam_setup:
            try:
                await context.bot.unpin_chat_message(
                    chat_id=user_id,
                    message_id=exam_setup['timer_message_id']
                )
            except Exception as e:
                logger.error(f"Error unpinning timer message: {e}")
        
        total_questions = exam_setup.get('total_questions')
        answered_count = len(exam_setup.get('answers', {}))
        
        course_name = exam_setup.get('course_name', 'Unknown')
        topic_name = exam_setup.get('topic_name', 'Unknown')
        
        await query.edit_message_text(
            text=f"📚 {course_name} - {topic_name}\n"
                 f"📝 Exam finished.\n"
                 f"⏰ Time spent: {elapsed_time:.2f} minutes\n"
                 f"📊 You answered {answered_count} out of {total_questions} questions.\n\n"
                 f"Please send the correct answers as a {total_questions}-digit string without spaces.\n\n"
                 f"📋 Example: for {total_questions} questions: {'1' * total_questions}"
        )

# مشاهده نتایج قبلی
async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            await update.message.reply_text("⚠️ Currently unable to access result history.")
            return
            
        cur = conn.cursor()
        
        cur.execute(
            "SELECT course_name, topic_name, created_at, score, start_question, end_question, exam_duration, elapsed_time, jalali_date, tehran_time FROM exams WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        )
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            result_text = "📋 Your recent exam results:\n\n"
            for i, result in enumerate(results, 1):
                try:
                    course_name, topic_name, date, score, start_q, end_q, duration, elapsed, jalali_date, tehran_time = result
                    
                    # بررسی مقادیر None
                    duration = duration or 0
                    elapsed = elapsed or 0
                    score = score or 0
                    start_q = start_q or 0
                    end_q = end_q or 0
                    course_name = course_name or 'Unknown'
                    topic_name = topic_name or 'Unknown'
                    jalali_date = jalali_date or 'Unknown'
                    tehran_time = tehran_time or 'Unknown'
                    
                    time_text = f"{elapsed:.1f} minutes of {duration} minutes" if duration and duration > 0 else f"{elapsed:.1f} minutes"
                    
                    result_text += f"{i}. {course_name} - {topic_name}\n"
                    result_text += f"   Questions {start_q}-{end_q} - Time: {time_text}\n"
                    result_text += f"   Score: {score:.2f}% - Date: {jalali_date} {tehran_time}\n\n"
                
                except Exception as e:
                    logger.error(f"Error processing result {i}: {e}")
                    result_text += f"{i}. Error processing result\n\n"
        else:
            result_text = "📭 No results to display."
            
    except Exception as e:
        logger.error(f"Error retrieving results: {e}")
        result_text = "⚠️ An error occurred while retrieving results."
    
    await update.message.reply_text(result_text)

# تابع اصلی
def main():
    if not init_db():
        logger.warning("Database initialization failed. The bot will work without database support.")
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot started with course/topic feature and jalali date...")
    application.run_polling()

if __name__ == "__main__":
    main()
