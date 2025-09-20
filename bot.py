import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# توکن ربات - باید از BotFather دریافت کنید
TOKEN = "8211286788:AAEf0nacvSZy7uXfUmcxNDkGquujQuvYzbE"

# اتصال به پایگاه داده PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL')  # یا آدرس کامل دیتابیس

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# ایجاد جدول در دیتابیس
def init_db():
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
async def handle_exam_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    exam_setup = context.user_data.get('exam_setup', {})
    
    if exam_setup.get('step') == 1:
        try:
            start_question = int(text)
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

# نمایش سوال با دکمه‌های اینلاین
async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_num):
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data=f"ans_{question_num}_1"),
            InlineKeyboardButton("2", callback_data=f"ans_{question_num}_2"),
            InlineKeyboardButton("3", callback_data=f"ans_{question_num}_3"),
            InlineKeyboardButton("4", callback_data=f"ans_{question_num}_4"),
        ],
        [InlineKeyboardButton("سوال بعدی →", callback_data=f"next_{question_num}")],
        [InlineKeyboardButton("اتمام آزمون", callback_data="finish_exam")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"❓ سوال شماره {question_num}:\nلطفاً گزینه صحیح را انتخاب کنید:",
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
        
        await query.edit_message_text(
            text=f"✅ پاسخ شما برای سوال {question_num}: گزینه {answer} ذخیره شد."
        )
    
    elif data.startswith("next_"):
        # رفتن به سوال بعدی
        current_question = exam_setup.get('current_question', exam_setup.get('start_question'))
        next_question = current_question + 1
        
        if next_question <= exam_setup.get('end_question'):
            exam_setup['current_question'] = next_question
            context.user_data['exam_setup'] = exam_setup
            await show_question(update, context, next_question)
        else:
            await query.edit_message_text(
                text="⚠️ این آخرین سوال آزمون است. برای اتمام آزمون دکمه 'اتمام آزمون' را بزنید."
            )
    
    elif data == "finish_exam":
        # اتمام آزمون و درخواست پاسخ‌های صحیح
        exam_setup['step'] = 'waiting_for_correct_answers'
        context.user_data['exam_setup'] = exam_setup
        
        await query.edit_message_text(
            text="📝 آزمون به پایان رسید. لطفاً پاسخ‌های صحیح را به صورت یک رشته اعداد و بدون فاصله ارسال کنید.\n\n" +
                 f"مثال: برای {exam_setup['total_questions']} سوال: 1234123412341234123412341"
        )

# پردازش پاسخ‌های صحیح و محاسبه نتایج
async def handle_correct_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    exam_setup = context.user_data.get('exam_setup', {})
    
    if exam_setup.get('step') == 'waiting_for_correct_answers':
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
        
        for i in range(exam_setup.get('start_question'), exam_setup.get('end_question') + 1):
            user_answer = user_answers.get(str(i))
            correct_answer = correct_answers[i - exam_setup.get('start_question')]
            
            if user_answer is None:
                unanswered_questions.append(i)
            elif user_answer == correct_answer:
                score += 1
            else:
                score -= 0.25  # نمره منفی
                wrong_questions.append(i)
        
        # محاسبه درصد
        percentage = (score / total_questions) * 100
        
        # ذخیره نتایج در دیتابیس
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
        
        # ارسال نتایج به کاربر
        result_text = f"""
        📊 نتایج آزمون شما:
        
        ✅ تعداد سوالات صحیح: {int(score * 4) / 4 if score > 0 else 0}
        ❌ تعداد سوالات غلط: {len(wrong_questions)}
        ⏸️ تعداد سوالات بی‌پاسخ: {len(unanswered_questions)}
        📈 درصد نمره: {percentage:.2f}%
        
        🔢 سوالات غلط: {', '.join(map(str, wrong_questions)) if wrong_questions else 'ندارد'}
        🔢 سوالات بی‌پاسخ: {', '.join(map(str, unanswered_questions)) if unanswered_questions else 'ندارد'}
        """
        
        await update.message.reply_text(result_text)
        
        # پاک کردن وضعیت آزمون
        context.user_data.pop('exam_setup', None)

# مشاهده نتایج قبلی
async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT created_at, score FROM exams WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
        (user_id,)
    )
    results = cur.fetchall()
    cur.close()
    conn.close()
    
    if results:
        result_text = "📋 آخرین نتایج آزمون‌های شما:\n\n"
        for i, (date, score) in enumerate(results, 1):
            result_text += f"{i}. تاریخ: {date.strftime('%Y-%m-%d %H:%M')} - نمره: {score:.2f}%\n"
    else:
        result_text = "📭 هیچ نتیجه‌ای برای نمایش وجود ندارد."
    
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exam_setup))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_correct_answers))
    
    # اجرای ربات
    application.run_polling()

if __name__ == "__main__":
    main()
