import logging
import requests
import json

import pandas as pd
import regex as re
from uuid import uuid4
from bs4 import BeautifulSoup

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, ParseMode, Update
from telegram.ext import Updater, CommandHandler, InlineQueryHandler, Filters, CallbackContext, MessageHandler, CallbackQueryHandler
from telegram.utils.helpers import escape_markdown

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)


class SizeButton:
    def __init__(self, text, value):
        self.text = text
        self.value = value


# Global Variables
selectedSizes: set[SizeButton] = set()
interval: float = 5


def unknown(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Sorry, I didn't understand that command.")


def start(update: Update, context: CallbackContext) -> None:
    try:
        shoe_url = context.args[0]
        if not shoe_url:
            update.message.reply_text(
                'Please provide desired shoe url to search')
            return

        chat_id = update.message.chat_id
        remove_job_if_exists(str(chat_id), context)
        context.job_queue.run_repeating(
            checkShoeSize, interval, context={'chat_id': chat_id, 'shoe_url': shoe_url}, name=str(chat_id))

    except (IndexError, ValueError):
        update.message.reply_text('Usage: /start <shoe_url>')

def getOutput(df: pd.DataFrame) -> str:
    sizes = df['localizedSize']
    is_included = sizes.isin(selectedSizes) & df['available']
    
    if is_included.any():
        filtered_df = sizes.loc[is_included]
        return 'The following sizes are AVAILABLE ✅: ' + ','.join(map(str, filtered_df.values.tolist()))
    else:
          return 'Your selected sizes are not available 😢❌'
    

def checkShoeSize(context: CallbackContext) -> None:
    """Send the alarm message."""
    job = context.job
    job_conext: dict = job.context
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0',
        'Accept': 'image/webp,*/*',
        'Accept-Language': 'fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3',
        'Connection': 'keep-alive',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
    }
    response = requests.get(job_conext.get('shoe_url'), headers=headers)
    data = json.loads(response.text)

    # In the json file, the following will give us the possible SKUs list
    skus = data['objects'][0]['productInfo'][0]['skus']
    # And the following their availability
    available_skus = data['objects'][0]['productInfo'][0]['availableGtins']
    
    df_skus = pd.DataFrame(skus)

    # Normalize the 'countrySpecifications' column
    normalized_df = pd.json_normalize(
        df_skus['countrySpecifications'].explode())
    normalized_df = normalized_df.drop('taxInfo.vat', axis=1)
    # Concatenate the normalized DataFrame with the original DataFrame
    result_df = pd.concat(
        [df_skus[['gtin', 'nikeSize', 'countrySpecifications']], normalized_df], axis=1)

    # Drop the original 'countrySpecifications' column
    result_df = result_df.drop('countrySpecifications', axis=1)

    df_available_skus = pd.DataFrame(available_skus)[['gtin', 'available']]
    # df_available_skus['available'] = df_available_skus['available'].replace({False: '❌', True: '✅'})

    # Here is finally the table with the available skus and their sizes
    df_merged = pd.merge(result_df, df_available_skus, on='gtin')
    # which can be saved in any format you want (xl, txt, csv, json...)
    context.bot.send_message(chat_id=job_conext.get('chat_id'), text=getOutput(df_merged))


def remove_job_if_exists(name: str, context: CallbackContext) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


def set_timer(update: Update, context: CallbackContext) -> None:
    """Add a job to the queue."""
    try:
        # args[0] should contain the time for the timer in seconds
        due = int(context.args[0])
        if due < 0:
            update.message.reply_text('Sorry we can not go back to future!')
            return

        interval = due
        text = 'Time successfully set!'
        update.message.reply_text(text)

    except (IndexError, ValueError):
        update.message.reply_text('Usage: /set <seconds>')


def set_sizes(update: Update, context: CallbackContext) -> None:
    """Add a job to the queue."""
    buttons: list[SizeButton] = [
        SizeButton('40 EU', 40),
        SizeButton('45 EU', 45),
        SizeButton('45.5 EU', 45.5),
        SizeButton('46 EU', 46),
    ]

    buttons_m = map(lambda button: InlineKeyboardButton(
        button.text, callback_data=button.value), buttons)

    keyboard: list[list[InlineKeyboardButton]] = [
        buttons_m,
    ]

    # args[0] should contain the time for the timer in seconds
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Choose sizes:', reply_markup=reply_markup)


def size_button(update: Update, context: CallbackContext) -> None:
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query

    if (float(query.data)):
        if (selectedSizes.__contains__(query.data)):
            selectedSizes.remove(query.data)
        else:
            selectedSizes.add(query.data)
        print(selectedSizes)

    query.answer()


def stop(update: Update, context: CallbackContext) -> None:
    """Remove the job if the user changed their mind."""
    chat_id = update.message.chat_id
    job_removed = remove_job_if_exists(str(chat_id), context)
    text = 'Searching successfully cancelled!' if job_removed else 'You have no active search.'
    update.message.reply_text(text)


def inlinequery(update: Update, context: CallbackContext) -> None:
    """Handle the inline query."""
    query = update.inline_query.query

    if query == "":
        return

    results = [
        InlineQueryResultArticle(
            id=str(uuid4()),
            title="Caps",
            input_message_content=InputTextMessageContent(query.upper()),
        ),
        InlineQueryResultArticle(
            id=str(uuid4()),
            title="Bold",
            input_message_content=InputTextMessageContent(
                f"*{escape_markdown(query)}*", parse_mode=ParseMode.MARKDOWN
            ),
        ),
        InlineQueryResultArticle(
            id=str(uuid4()),
            title="Italic",
            input_message_content=InputTextMessageContent(
                f"_{escape_markdown(query)}_", parse_mode=ParseMode.MARKDOWN
            ),
        ),
    ]

    update.inline_query.answer(results)


def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(
        token="6149915835:AAFA5SXjXN_imqbzfKIedQ2xOibCFWfvk3E", use_context=True)

    updater.bot.setMyCommands([
        BotCommand('start', 'start seraching for shoe sizes'),
        BotCommand('stop', 'stop existing search for shoe sizes'),
        BotCommand('set_interval', 'set interval for fetching sizes from Nike'),
        BotCommand('set_sizes', 'set your preferred sizes'),
    ])

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CallbackQueryHandler(size_button))
    dispatcher.add_handler(CommandHandler("stop", stop))
    dispatcher.add_handler(CommandHandler("set_interval", set_timer))
    dispatcher.add_handler(CommandHandler("set_sizes", set_sizes))

    # on non command i.e message - echo the message on Telegram
    dispatcher.add_handler(MessageHandler(Filters.command, unknown))

    # on non command i.e message - echo the message on Telegram
    dispatcher.add_handler(InlineQueryHandler(inlinequery))

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
