import logging
import re
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# حالت‌های مکالمه
SETTING_EXAM, ENTERING_ANSWERS = range(2)

# ساختار ذخیره اطلاعات کاربران
user_data = {}

class Exam:
    def __init__(self, duration, question_count, start_number, exam_type, book_title):
        self.duration = duration
        self.question_count = question_count
        self.start_number = start_number
        self.exam_type = exam_type
        self.book_title = book_title
        self.correct_answers = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("User %s started the conversation.", user.first_name)
    
    # ایجاد صفحه اولیه شبیه به تصویر
    welcome_message = (
        "ارزیابی آزمون\n\n"
        "میتعلم تیک برنام\n"
        "کلید هام رو به پاسخنامه تیک برن\n\n"
        "میتعلم رشته وارد کنم\n"
        "کلید هام رو به صورت رشته ای از اعداد وارد کن\n\n"
        "برای شروع آزمون جدید، از /exam استفاده کنید."
    )
    
    await update.message.reply_text(welcome_message)
    return ConversationHandler.END

async def exam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("User %s is creating a new exam.", user.first_name)
    
    # ایجاد صفحه ایجاد پاسخنامه شبیه به تصویر
    exam_setup_message = (
        "ایجاد پاسخنامه\n\n"
        "- مدت زمان انجام آزمون را وارد نمایید (دقیقه) *\n\n"
        "- تعداد سوالات را وارد نمایید *\n\n"
        "- شماره اولین سوال را وارد نمایید *\n\n"
        "- نوع آزمون را انتخاب نمایید *\n"
        "  - آزمون محیطی\n"
        "  - آزمون با سوالات فرد\n"
        "  - آزمون با سوالات زوج\n"
        "  - آزمون با سوالات دلخواه\n\n"
        "- عنوان کتاب را وارد نمایید *\n\n"
        "لطفاً مدت زمان آزمون را وارد کنید:"
    )
    
    await update.message.reply_text(exam_setup_message)
    return SETTING_EXAM

async def set_exam_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    duration = update.message.text
    
    if not duration.isdigit() or int(duration) <= 0:
        await update.message.reply_text("لطفاً یک عدد صحیح مثبت برای مدت زمان آزمون وارد کنید:")
        return SETTING_EXAM
    
    user_data[user.id] = {'exam_setup': {'duration': int(duration)}}
    
    await update.message.reply_text("تعداد سوالات را وارد نمایید:")
    return SETTING_EXAM

async def set_question_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    question_count = update.message.text
    
    if not question_count.isdigit() or int(question_count) <= 0:
        await update.message.reply_text("لطفاً یک عدد صحیح مثبت برای تعداد سوالات وارد کنید:")
        return SETTING_EXAM
    
    user_data[user.id]['exam_setup']['question_count'] = int(question_count)
    
    await update.message.reply_text("شماره اولین سوال را وارد نمایید:")
    return SETTING_EXAM

async def set_start_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    start_number = update.message.text
    
    if not start_number.isdigit() or int(start_number) <= 0:
        await update.message.reply_text("لطفاً یک عدد صحیح مثبت برای شماره اولین سوال وارد کنید:")
        return SETTING_EXAM
    
    user_data[user.id]['exam_setup']['start_number'] = int(start_number)
    
    # ایجاد کیبورد برای انتخاب نوع آزمون
    keyboard = [
        ['آزمون محیطی', 'آزمون با سوالات فرد'],
        ['آزمون با سوالات زوج', 'آزمون با سوالات دلخواه']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    
    await update.message.reply_text("نوع آزمون را انتخاب نمایید:", reply_markup=reply_markup)
    return SETTING_EXAM

async def set_exam_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    exam_type = update.message.text
    
    user_data[user.id]['exam_setup']['exam_type'] = exam_type
    
    await update.message.reply_text("عنوان کتاب را وارد نمایید:", reply_markup=ReplyKeyboardRemove())
    return SETTING_EXAM

async def set_book_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    book_title = update.message.text
    
    user_data[user.id]['exam_setup']['book_title'] = book_title
    
    # ایجاد نمونه آزمون
    setup = user_data[user.id]['exam_setup']
    exam = Exam(
        duration=setup['duration'],
        question_count=setup['question_count'],
        start_number=setup['start_number'],
        exam_type=setup['exam_type'],
        book_title=setup['book_title']
    )
    
    user_data[user.id]['current_exam'] = exam
    
    # درخواست کلید پاسخ‌ها
    await update.message.reply_text(
        f"آزمون با مشخصات زیر ایجاد شد:\n"
        f"مدت زمان: {exam.duration} دقیقه\n"
        f"تعداد سوالات: {exam.question_count}\n"
        f"شماره شروع: {exam.start_number}\n"
        f"نوع آزمون: {exam.exam_type}\n"
        f"عنوان کتاب: {exam.book_title}\n\n"
        f"لطفاً کلید پاسخ‌های صحیح را به صورت یک رشته اعداد وارد کنید (مثال: 12343214321432143214):"
    )
    
    return ENTERING_ANSWERS

async def set_correct_answers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    answers = update.message.text
    
    # اعتبارسنجی پاسخ‌ها
    if not re.match(r'^[1-4]+$', answers):
        await update.message.reply_text("لطفاً فقط اعداد 1 تا 4 وارد کنید (مثال: 12343214321432143214):")
        return ENTERING_ANSWERS
    
    exam = user_data[user.id]['current_exam']
    if len(answers) != exam.question_count:
        await update.message.reply_text(f"تعداد پاسخ‌ها ({len(answers)}) با تعداد سوالات ({exam.question_count}) مطابقت ندارد. لطفاً مجدداً وارد کنید:")
        return ENTERING_ANSWERS
    
    exam.correct_answers = answers
    user_data[user.id]['current_exam'] = exam
    
    await update.message.reply_text(
        f"کلید پاسخ‌ها ثبت شد.\n\n"
        f"اکنون پاسخ‌های خود را به صورت یک رشته اعداد وارد کنید (مثال: 12431243124312431243):"
    )
    
    return ENTERING_ANSWERS

async def calculate_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    user_answers = update.message.text
    
    # اعتبارسنجی پاسخ‌های کاربر
    if not re.match(r'^[0-4]+$', user_answers):
        await update.message.reply_text("لطفاً فقط اعداد 0 تا 4 وارد کنید (0 برای سوالات بی‌پاسخ):")
        return ENTERING_ANSWERS
    
    exam = user_data[user.id]['current_exam']
    if len(user_answers) != exam.question_count:
        await update.message.reply_text(f"تعداد پاسخ‌ها ({len(user_answers)}) با تعداد سوالات ({exam.question_count}) مطابقت ندارد. لطفاً مجدداً وارد کنید:")
        return ENTERING_ANSWERS
    
    # محاسبه نتایج
    correct_count = 0
    wrong_count = 0
    blank_count = 0
    wrong_questions = []
    blank_questions = []
    
    for i, (correct, user_answer) in enumerate(zip(exam.correct_answers, user_answers)):
        question_number = exam.start_number + i
        
        if user_answer == '0':
            blank_count += 1
            blank_questions.append(question_number)
        elif user_answer == correct:
            correct_count += 1
        else:
            wrong_count += 1
            wrong_questions.append(question_number)
    
    # محاسبه نمره با در نظر گرفتن نمره منفی (هر 3 غلط، 1 correct حذف می‌شود)
    net_correct = correct_count - (wrong_count // 3)
    score_percentage = max(0, (net_correct / exam.question_count) * 100)
    
    # ایجاد گزارش نتایج
    result_message = (
        f"نتایج آزمون:\n\n"
        f"📊 درصد: {score_percentage:.2f}%\n"
        f"✅ صحیح: {correct_count}\n"
        f"❌ غلط: {wrong_count}\n"
        f"➖ نزده: {blank_count}\n\n"
    )
    
    if wrong_questions:
        result_message += f"سوالات غلط: {', '.join(map(str, wrong_questions))}\n\n"
    
    if blank_questions:
        result_message += f"سوالات نزده: {', '.join(map(str, blank_questions))}\n\n"
    
    result_message += "برای شروع آزمون جدید، از /exam استفاده کنید."
    
    await update.message.reply_text(result_message)
    
    # پاکسازی داده‌های کاربر
    if user.id in user_data:
        del user_data[user.id]
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.message.from_user
    logger.info("User %s canceled the conversation.", user.first_name)
    
    # پاکسازی داده‌های کاربر
    if user.id in user_data:
        del user_data[user.id]
    
    await update.message.reply_text(
        "عملیات لغو شد.",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return ConversationHandler.END

def main() -> None:
    # ایجاد اپلیکیشن و اضافه کردن هندلرها
    application = Application.builder().token("8211286788:AAEf0nacvSZy7uXfUmcxNDkGquujQuvYzbE").build()
    
    # هندلر مکالمه برای ایجاد آزمون و وارد کردن پاسخ‌ها
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('exam', exam_command)],
        states={
            SETTING_EXAM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_exam_duration),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_question_count),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_start_number),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_exam_type),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_book_title),
            ],
            ENTERING_ANSWERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_correct_answers),
                MessageHandler(filters.TEXT & ~filters.COMMAND, calculate_results),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    
    # اجرای ربات
    application.run_polling()

if __name__ == '__main__':
    main()
