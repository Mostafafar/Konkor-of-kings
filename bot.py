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

# توکن ربات - باید از BotFather دریافت کنید
TOKEN = "8211286788:AAEf0nacvSZy7uXfUmcxNDkGquujQuvYzbE"

# تنظیمات دیتابیس - با اطلاعات واقعی جایگزین کنید
DB_CONFIG = {
    'dbname': 'exam_bot',
    'user': 'bot_user',
    'password': 'your_password',
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

# ایجاد جدول در دیتابیس
def init_db():
    try:
        conn = get_db_connection()
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
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

# مدیریت دستور start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    welcome_text = """
    🤖 به ربات آزمون تستی خوش آمدید!

    📝 برای شروع یک آزمون جدید، از دستور /new_exam استفاده کنید.
    📊 برای مشاهده نتایج قبلی، از دستور /results استفاده کنید.
    """
    await update.message.reply_text(welcome_text)

# ایجاد آزمون جدید
async def new_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # ذخیره وضعیت کاربر برای مراحل بعدی
    context.user_data['exam_setup'] = {'step': 1}
    
    await update.message.reply_text(
        "🔢 لطفاً شماره اولین سوال را وارد کنید:"
    )

# پردازش مراحل ایجاد آزمون
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    exam_setup = context.user_data.get('exam_setup', {})
    
    if 'exam_setup' not in context.user_data:
        await update.message.reply_text("لطفا ابتدا با دستور /new_exam یک آزمون جدید شروع کنید.")
        return
    
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
            exam_setup['end_question'] = end_question
            exam_setup['total_questions'] = total_questions
            exam_setup['step'] = 3
            exam_setup['current_question'] = start_question
            exam_setup['answers'] = {}
            context.user_data['exam_setup'] = exam_setup
            
            # نمایش اولین سوال
            await show_question(update, context, start_question)
            
        except ValueError:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید.")
    
    elif exam_setup.get('step') == 'waiting_for_correct_answers':
        total_questions = exam_setup.get('total_questions')
        
        # بررسی صحت فرمت پاسخ‌ها
        if len(text) != total_questions or not text.isdigit():
            await update.message.reply_text(
                f"❌ رشته ارسالی باید شامل {total_questions} عدد باشد. لطفاً مجدداً وارد کنید:"
            )
            return
        
        # تبدیل رشته به لیست اعداد
        correct_answers = [int(char) for char in text]
        
        # محاسبه نتایج
        user_answers = exam_setup.get('answers', {})
        score = 0
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
                score += 1
            else:
                score -= 0.25  # نمره منفی
                wrong_questions.append(i)
        
        # محاسبه درصد
        percentage = (score / total_questions) * 100 if total_questions > 0 else 0
        
        # ذخیره نتایج در دیتابیس
        try:
            conn = get_db_connection()
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
                    text,
                    percentage,
                    str(wrong_questions),
                    str(unanswered_questions)
                )
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving to database: {e}")
            await update.message.reply_text("⚠️ خطایی در ذخیره نتایج رخ داد. لطفاً بعداً مجدداً تلاش کنید.")
        
        # ارسال نتایج به کاربر
        correct_count = int(score * 4) // 4 if score > 0 else 0
        wrong_count = len(wrong_questions)
        unanswered_count = len(unanswered_questions)
        
        result_text = f"""
        📊 نتایج آزمون شما:
        
        ✅ تعداد سوالات صحیح: {correct_count}
        ❌ تعداد سوالات غلط: {wrong_count}
        ⏸️ تعداد سوالات بی‌پاسخ: {unanswered_count}
        📈 درصد نمره: {percentage:.2f}%
        
        🔢 سوالات غلط: {', '.join(map(str, wrong_questions)) if wrong_questions else 'ندارد'}
        🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'ندارد'}
        """
        
        await update.message.reply_text(result_text)
        
        # پاک کردن وضعیت آزمون
        context.user_data.pop('exam_setup', None)

# نمایش سوال با دکمه‌های اینلاین
async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_num):
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data=f"ans_{question_num}_1"),
            InlineKeyboardButton("2", callback_data=f"ans_{question_num}_2"),
            InlineKeyboardButton("3", callback_data=f"ans_{question_num}_3"),
            InlineKeyboardButton("4", callback_data=f"ans_{question_num}_4"),
        ]
    ]
    
    # اضافه کردن دکمه‌های navigation
    exam_setup = context.user_data.get('exam_setup', {})
    start_question = exam_setup.get('start_question')
    end_question = exam_setup.get('end_question')
    
    nav_buttons = []
    if question_num > start_question:
        nav_buttons.append(InlineKeyboardButton("← سوال قبلی", callback_data=f"prev_{question_num}"))
    if question_num < end_question:
        nav_buttons.append(InlineKeyboardButton("سوال بعدی →", callback_data=f"next_{question_num}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("اتمام آزمون", callback_data="finish_exam")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # بررسی اگر پاسخ قبلی داده شده
    user_answer = exam_setup.get('answers', {}).get(str(question_num))
    answer_status = f" (پاسخ داده شده: {user_answer})" if user_answer else ""
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"❓ سوال شماره {question_num}:{answer_status}\nلطفاً گزینه صحیح را انتخاب کنید:",
        reply_markup=reply_markup
    )

# مدیریت پاسخ‌های اینلاین
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    exam_setup = context.user_data.get('exam_setup', {})
    
    if data.startswith("ans_"):
        # پردازش پاسخ کاربر
        parts = data.split("_")
        question_num = int(parts[1])
        answer = int(parts[2])
        
        # ذخیره پاسخ
        exam_setup['answers'][str(question_num)] = answer
        context.user_data['exam_setup'] = exam_setup
        
        # نمایش مجدد سوال با وضعیت به روز شده
        await show_question(update, context, question_num)
        await query.delete_message()
    
    elif data.startswith("next_"):
        # رفتن به سوال بعدی
        parts = data.split("_")
        current_question = int(parts[1])
        next_question = current_question + 1
        
        if next_question <= exam_setup.get('end_question'):
            exam_setup['current_question'] = next_question
            context.user_data['exam_setup'] = exam_setup
            await show_question(update, context, next_question)
            await query.delete_message()
        else:
            await query.edit_message_text(
                text="⚠️ این آخرین سوال آزمون است. برای اتمام آزمون دکمه 'اتمام آزمون' را بزنید."
            )
    
    elif data.startswith("prev_"):
        # رفتن به سوال قبلی
        parts = data.split("_")
        current_question = int(parts[1])
        prev_question = current_question - 1
        
        if prev_question >= exam_setup.get('start_question'):
            exam_setup['current_question'] = prev_question
            context.user_data['exam_setup'] = exam_setup
            await show_question(update, context, prev_question)
            await query.delete_message()
    
    elif data == "finish_exam":
        # اتمام آزمون و درخواست پاسخ‌های صحیح
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
        total_questions = exam_setup.get('total_questions')
        await query.edit_message_text(
            text="📝 آزمون به پایان رسید. لطفاً پاسخ‌های صحیح را به صورت یک رشته اعداد و بدون فاصله ارسال کنید.\n\n" +
                 f"مثال: برای {total_questions} سوال: {'1' * total_questions}"
        )

# مشاهده نتایج قبلی
async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
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
                result_text += f"{i}. {start_q}-{end_q} - تاریخ: {date.strftime('%Y-%m-%d %H:%M')} - نمره: {score:.2f}%\n"
        else:
            result_text = "📭 هیچ نتیجه‌ای برای نمایش وجود ندارد."
    except Exception as e:
        logger.error(f"Error retrieving results: {e}")
        result_text = "⚠️ خطایی در دریافت نتایج رخ داد."
    
    await update.message.reply_text(result_text)

# تابع اصلی
def main():
    # ایجاد جدول در دیتابیس
    init_db()
    
    # ایجاد اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # اضافه کردن handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_exam", new_exam))
    application.add_handler(CommandHandler("results", show_results))
    application.add_handler(CallbackQueryHandler(handle_answer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # اجرای ربات
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
