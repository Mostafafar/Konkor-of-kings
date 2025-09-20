import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime

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
    1. با /new_exam آزمون جدید شروع کنید
    2. شماره اولین و آخرین سوال را وارد کنید
    3. به سوالات با دکمه‌ها پاسخ دهید
    4. در پایان، پاسخ‌های صحیح را وارد کنید
    5. نتایج را مشاهده کنید
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

# نمایش تمام سوالات به صورت همزمان
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
        message_text += f"{question_num}){status}\n"
        
        # ایجاد دکمه‌های گزینه‌ها برای هر سوال با شماره سوال
        question_buttons = []
        for option in [1, 2, 3, 4]:
            # اگر این گزینه قبلاً انتخاب شده، علامت ✅ نشان داده شود
            button_text = f"{question_num}-{option} ✅" if current_answer == option else f"{question_num}-{option}"
            question_buttons.append(InlineKeyboardButton(button_text, callback_data=f"ans_{question_num}_{option}"))
        
        keyboard.append(question_buttons)
    
    # اضافه کردن دکمه اتمام آزمون
    keyboard.append([InlineKeyboardButton("🎯 اتمام آزمون و ارسال پاسخ‌ها", callback_data="finish_exam")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # ارسال پیام با تمام سوالات
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message_text,
        reply_markup=reply_markup
    )

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
            if total_questions > 50:  # محدودیت برای جلوگیری از پیام بسیار طولانی
                await update.message.reply_text("❌ حداکثر تعداد سوالات مجاز 50 عدد است.")
                return
                
            exam_setup['end_question'] = end_question
            exam_setup['total_questions'] = total_questions
            exam_setup['step'] = 3
            exam_setup['answers'] = {}
            context.user_data['exam_setup'] = exam_setup
            
            # نمایش تمام سوالات به صورت همزمان
            await show_all_questions(update, context)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 'waiting_for_correct_answers':
        total_questions = exam_setup.get('total_questions')
        
        # حذف فاصله و کاراکترهای غیرعددی
        cleaned_text = ''.join(filter(str.isdigit, text))
        
        # بررسی صحت فرمت پاسخ‌ها
        if len(cleaned_text) != total_questions:
            await update.message.reply_text(
                f"❌ رشته ارسالی باید شامل {total_questions} عدد باشد. شما {len(cleaned_text)} عدد وارد کردید. لطفاً مجدداً وارد کنید:"
            )
            return
        
        # تبدیل رشته به لیست اعداد
        correct_answers = [int(char) for char in cleaned_text]
        
        # محاسبه نتایج
        user_answers = exam_setup.get('answers', {})
        correct_questions = []
        wrong_questions = []
        unanswered_questions = []
        
        start_q = exam_setup.get('start_question')
        end_q = exam_setup.get('end_question')
        
        # تشخیص سوالات صحیح، غلط و بی‌پاسخ
        for i in range(start_q, end_q + 1):
            user_answer = user_answers.get(str(i))
            correct_answer = correct_answers[i - start_q]
            
            if user_answer is None:
                unanswered_questions.append(i)
            elif user_answer == correct_answer:
                correct_questions.append(i)
            else:
                wrong_questions.append(i)
        
        # محاسبه بر اساس روش عکس
        correct_count = len(correct_questions)
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)
        
        # درصد بدون نمره منفی
        percentage_without_penalty = (correct_count / total_questions) * 100 if total_questions > 0 else 0
        
        # محاسبه نمره با اعمال نمره منفی (هر 3 غلط، 1 صحیح را حذف می‌کند)
        penalty_deduction = wrong_count // 3
        final_score = max(0, correct_count - penalty_deduction)
        
        # درصد با نمره منفی
        final_percentage = (final_score / total_questions) * 100 if total_questions > 0 else 0
        
        # ذخیره نتایج در دیتابیس (اگر ممکن باشد)
        saved_to_db = False
        try:
            conn = get_db_connection()
            if conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO exams 
                    (user_id, start_question, end_question, total_questions, answers, correct_answers, score, wrong_questions, unanswered_questions)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        exam_setup.get('start_question'),
                        exam_setup.get('end_question'),
                        total_questions,
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
        
        # ارسال نتایج به کاربر مطابق عکس
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
        
        # پاک کردن وضعیت آزمون
        context.user_data.pop('exam_setup', None)

# مدیریت پاسخ‌های اینلاین
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if 'exam_setup' not in context.user_data:
        await query.edit_message_text("⚠️ لطفا ابتدا با /new_exam یک آزمون جدید شروع کنید.")
        return
        
    exam_setup = context.user_data['exam_setup']
    
    if data.startswith("ans_"):
        # پردازش پاسخ کاربر
        parts = data.split("_")
        question_num = int(parts[1])
        answer = int(parts[2])
        
        # ذخیره پاسخ
        exam_setup['answers'][str(question_num)] = answer
        context.user_data['exam_setup'] = exam_setup
        
        # نمایش مجدد تمام سوالات با وضعیت به روز شده
        await show_all_questions(update, context)
        await query.delete_message()
    
    elif data == "finish_exam":
        # اتمام آزمون و درخواست پاسخ‌های صحیح
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
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
            "SELECT created_at, score, start_question, end_question FROM exams WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        )
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            result_text = "📋 آخرین نتایج آزمون‌های شما:\n\n"
            for i, (date, score, start_q, end_q) in enumerate(results, 1):
                result_text += f"{i}. سوالات {start_q}-{end_q} - تاریخ: {date.strftime('%Y-%m-%d %H:%M')} - نمره: {score:.2f}%\n"
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
    - محدوده سوالات را مشخص کنید (مثلاً ۱ تا ۲۰)
    - با دکمه‌ها به سوالات پاسخ دهید
    - در پایان، پاسخ‌های صحیح را وارد کنید
    - نتایج را مشاهده کنید
    
    ⚠️ توجه: هر ۳ پاسخ غلط، ۱ پاسخ صحیح را حذف می‌کند.
    """
    await update.message.reply_text(help_text)

# تابع اصلی
def main():
    # ایجاد جدول در دیتابیس
    if not init_db():
        logger.warning("Database initialization failed. The bot will work without database support.")
    
    # ایجاد اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # اجرای ربات
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
