import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta

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
        cur.execute('''
            CREATE TABLE IF NOT EXISTS exams (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                start_question INTEGER,
                end_question INTEGER,
                total_questions INTEGER,
                exam_duration INTEGER,
                answers TEXT,
                correct_answers TEXT,
                score REAL,
                wrong_questions TEXT,
                unanswered_questions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return False

# مدیریت دستور start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome_text = """
    🤖 به ربات آزمون تستی خوش آمدید!

    📝 برای شروع یک آزمون جدید، از دستور /new_exam استفاده کنید.
    📊 برای مشاهده نتایج قبلی، از دستور /results استفاده کنید.
    🆘 برای راهنما، از دستور /help استفاده کنید.
    
    🎯 نحوه استفاده:
    1. با /new_exam شروع کنید
    2. محدوده سوالات و زمان آزمون را مشخص کنید
    3. با دکمه‌ها به سوالات پاسخ دهید
    4. در پایان، پاسخ‌های صحیح را وارد کنید
    5. نتایج را مشاهده کنید
    
    ⏰ دارای تایمر پیشرفته برای مدیریت زمان آزمون
    """
    await update.message.reply_text(welcome_text)

# ایجاد آزمون جدید
async def new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # پاک کردن وضعیت قبلی
    context.user_data.pop('exam_setup', None)
    
    # ایجاد وضعیت جدید
    context.user_data['exam_setup'] = {'step': 1}
    
    await update.message.reply_text(
        "🔢 لطفاً شماره اولین سوال را وارد کنید:"
    )

# نمایش تمام سوالات به صورت همزمان با فرمت جدید
async def show_all_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exam_setup = context.user_data['exam_setup']
    start_question = exam_setup.get('start_question')
    end_question = exam_setup.get('end_question')
    user_answers = exam_setup.get('answers', {})
    
    message_text = "📝 لطفاً به سوالات پاسخ دهید:\n\n"
    
    # ایجاد دکمه‌های اینلاین برای تمام سوالات
    keyboard = []
    
    for question_num in range(start_question, end_question + 1):
        # وضعیت پاسخ فعلی
        current_answer = user_answers.get(str(question_num))
        status = f" ✅ (گزینه {current_answer})" if current_answer else ""
        
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
    
    # اضافه کردن دکمه اتمام آزمون
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
    
    # فقط نوار پیشرفت و زمان باقیمانده نمایش داده شود
    timer_text = f"⏳ باقیمانده: {minutes:02d}:{seconds:02d}\n{progress_bar}"
    
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
    
    # ارسال پیام اتمام زمان
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⏰ زمان آزمون به پایان رسید!\n"
                 f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
                 f"لطفاً پاسخ‌های صحیح را به صورت یک رشته {total_questions} رقمی و بدون فاصله ارسال کنید.\n\n"
                 f"📋 مثال: برای {total_questions} سوال: {'1' * total_questions}"
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

# پردازش مراحل ایجاد آزمون
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if 'exam_setup' not in context.user_data:
        await update.message.reply_text("لطفا ابتدا با دستور /new_exam یک آزمون جدید شروع کنید.")
        return
    
    exam_setup = context.user_data['exam_setup']
    
    if exam_setup.get('step') == 1:
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
            if total_questions > 50:
                await update.message.reply_text("❌ حداکثر تعداد سوالات مجاز 50 عدد است.")
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
            
            # نمایش تمام سوالات به صورت همزمان
            await show_all_questions(update, context)
            
            # نمایش تایمر پین شده
            await show_pinned_timer(context, user_id, exam_setup)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 'waiting_for_correct_answers':
        total_questions = exam_setup.get('total_questions')
        
        # حذف فاصله و کاراکترهای غیرعددی
        cleaned_text = ''.join(filter(str.isdigit, text))
        
        if len(cleaned_text) != total_questions:
            await update.message.reply_text(
                f"❌ رشته ارسالی باید شامل {total_questions} عدد باشد. شما {len(cleaned_text)} عدد وارد کردید. لطفاً مجدداً وارد کنید:"
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
        
        correct_count = len(correct_questions)
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)
        
        percentage_without_penalty = (correct_count / total_questions) * 100 if total_questions > 0 else 0
        
        penalty_deduction = wrong_count // 3
        final_score = max(0, correct_count - penalty_deduction)
        final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0
        
        # ذخیره نتایج در دیتابیس
        saved_to_db = False
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO exams 
                    (user_id, start_question, end_question, total_questions, exam_duration, answers, correct_answers, score, wrong_questions, unanswered_questions)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        exam_setup.get('start_question'),
                        exam_setup.get('end_question'),
                        total_questions,
                        exam_setup.get('exam_duration'),
                        str(user_answers),
                        cleaned_text,
                        final_percentage,
                        str(wrong_questions),
                        str(unanswered_questions)
                    )
                )
                conn.commit()
                cur.close()
                conn.close()
                saved_to_db = True
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
        
        # ارسال نتایج
        result_text = f"""
📊 نتایج آزمون شما:

✅ تعداد پاسخ صحیح: {correct_count}
❌ تعداد پاسخ اشتباه: {wrong_count}
⏸️ تعداد بی‌پاسخ: {unanswered_count}
📝 تعداد کل سوالات: {total_questions}

📈 درصد بدون نمره منفی: {percentage_without_penalty:.2f}%
📉 درصد با نمره منفی: {final_percentage:.2f}%

🔢 سوالات صحیح: {', '.join(map(str, correct_questions)) if correct_questions else 'ندارد'}
🔢 سوالات غلط: {', '.join(map(str, wrong_questions)) if wrong_questions else 'ندارد'}
🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'ندارد'}

💡 نکته: هر ۳ پاسخ اشتباه، ۱ پاسخ صحیح را خنثی می‌کند.
"""
        
        if not saved_to_db:
            result_text += "\n\n⚠️ نتایج در پایگاه داده ذخیره نشد (مشکل اتصال)."
        
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
        await query.edit_message_text("⚠️ لطفا ابتدا با /new_exam یک آزمون جدید شروع کنید.")
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
        
        await show_all_questions(update, context)
        await query.delete_message()
    
    elif data == "finish_exam":
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
        # به روزرسانی در bot_data نیز
        if 'user_exams' in context.bot_data and user_id in context.bot_data['user_exams']:
            context.bot_data['user_exams'][user_id] = exam_setup
        
        # حذف تایمر
        job_name = f"timer_{user_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        
        total_questions = exam_setup.get('total_questions')
        answered_count = len(exam_setup.get('answers', {}))
        
        await query.edit_message_text(
            text=f"📝 آزمون به پایان رسید.\n"
                 f"📊 شما به {answered_count} از {total_questions} سوال پاسخ داده‌اید.\n\n"
                 f"لطفاً پاسخ‌های صحیح را به صورت یک رشته {total_questions} رقمی و بدون فاصله ارسال کنید.\n\n"
                 f"📋 مثال: برای {total_questions} سوال: {'1' * total_questions}"
        )

# مشاهده نتایج قبلی
async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if conn is None:
            await update.message.reply_text("⚠️ در حال حاضر امکان دسترسی به تاریخچه نتایج وجود ندارد.")
            return
            
        cur = conn.cursor()
        cur.execute(
            "SELECT created_at, score, start_question, end_question, exam_duration FROM exams WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        )
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            result_text = "📋 آخرین نتایج آزمون‌های شما:\n\n"
            for i, (date, score, start_q, end_q, duration) in enumerate(results, 1):
                duration_text = f"{duration} دقیقه" if duration > 0 else "بدون محدودیت"
                result_text += f"{i}. سوالات {start_q}-{end_q} - زمان: {duration_text} - نمره: {score:.2f}% - تاریخ: {date.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            result_text = "📭 هیچ نتیجه‌ای برای نمایش وجود ندارد."
    except Exception as e:
        logger.error(f"Error retrieving results: {e}")
        result_text = "⚠️ خطایی در دریافت نتایج رخ داد."
    
    await update.message.reply_text(result_text)

# راهنمای استفاده
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    📖 راهنمای استفاده از ربات آزمون تستی:
    
    1. /start - شروع کار با ربات
    2. /new_exam - ایجاد یک آزمون جدید
    3. /results - مشاهده نتایج قبلی
    4. /help - نمایش این راهنما
    
    🎯 نحوه کار:
    - با /new_exam شروع کنید
    - محدوده سوالات و زمان آزمون را مشخص کنید
    - با دکمه‌ها به سوالات پاسخ دهید
    - در پایان، پاسخ‌های صحیح را وارد کنید
    - نتایج را مشاهده کنید
    
    ⏰ ویژگی‌های تایمر:
    - نمایش زمان باقیمانده به صورت زنده
    - پیام تایمر پین شده در بالای چت
    - نوار پیشرفت گرافیکی
    - اتمام خودکار آزمون هنگام اتمام زمان
    
    ⚠️ توجه: هر ۳ پاسخ غلط، ۱ پاسخ صحیح را حذف می‌کند.
    """
    await update.message.reply_text(help_text)

# تابع اصلی
def main():
    if not init_db():
        logger.warning("Database initialization failed. The bot will work without database support.")
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot started with pinned timer feature...")
    application.run_polling()

if __name__ == "__main__":
    main()
