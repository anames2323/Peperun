# Для чего нужен этот файл?
# Тут храняться сохранения, админ панель, и тд.

import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
import json
import requests
import os
import threading

TOKEN = "urtoken"
ADMIN_ID = 1608641992
WEB_APP_URL = "urltosite"
DATA_FILE = 'data.json'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "users": {},
            "flags": {
                "100_per_rarity_super": False,
                "100_per_rarity": False,
                "double_chances": False,
                "trible_chances": False,
            },
            "event": None
        }
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "users": {},
            "flags": {
                "100_per_rarity_super": False,
                "100_per_rarity": False,
                "double_chances": False,
                "trible_chances": False,
            },
            "event": None
        }

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user(user_id):
    data = load_data()
    user = data["users"].get(str(user_id))
    if not user:
        user = {
            "balance": 10000,
            "inventory": [],
            "stats": {
                "cases_opened": 0,
                "best_drop": None,
                "case_open_stats": {}
            }
        }
        data["users"][str(user_id)] = user
        save_data(data)
    return user

@app.route('/api/get_user_data', methods=['GET'])
def get_user_data():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    data = load_data()
    user = get_user(user_id)
    return jsonify({
        "user_data": user,
        "flags": data["flags"],
        "event": data["event"]
    })

@app.route('/api/open_case', methods=['POST'])
def open_case():
    try:
        data = request.json
        user_id = data.get('user_id')
        case_id = data.get('case_id')
        cases_data = data.get('cases_data')

        if not user_id or not case_id or not cases_data:
            return jsonify({"error": "Invalid data"}), 400

        user_data = get_user(user_id)
        flags = load_data()["flags"]
        current_case = next((c for c in cases_data if c['id'] == case_id), None)

        if not current_case:
            return jsonify({"error": "Case not found"}), 404

        if user_data['balance'] < current_case['price']:
            return jsonify({"error": "Insufficient balance"}), 402

        user_data['balance'] -= current_case['price']

        modified_items = []
        if flags.get('100_per_rarity_super'):
            modified_items = [item for item in current_case['items'] if item['rarity_color'] == 'super-legendary']
        elif flags.get('100_per_rarity'):
            modified_items = [item for item in current_case['items'] if item['rarity_color'] in ['super-legendary', 'legendary']]
        elif flags.get('trible_chances'):
            rare_and_above = [item for item in current_case['items'] if item['rarity_color'] in ['super-legendary', 'legendary', 'epic', 'rare']]
            common_and_unusual = [item for item in current_case['items'] if item['rarity_color'] in ['common', 'unusual']]
            total_rare_chance = sum(item['chance'] for item in rare_and_above)
            total_common_chance = sum(item['chance'] for item in common_and_unusual)

            for item in rare_and_above:
                item['chance'] *= 3

            new_total_rare_chance = sum(item['chance'] for item in rare_and_above)
            adjustment = new_total_rare_chance - total_rare_chance

            adjustment_ratio = (total_common_chance - adjustment) / total_common_chance if total_common_chance > 0 else 0
            for item in common_and_unusual:
                item['chance'] *= adjustment_ratio

            modified_items = rare_and_above + common_and_unusual
        elif flags.get('double_chances'):
            rare_and_above = [item for item in current_case['items'] if item['rarity_color'] in ['super-legendary', 'legendary', 'epic', 'rare']]
            common_and_unusual = [item for item in current_case['items'] if item['rarity_color'] in ['common', 'unusual']]
            total_rare_chance = sum(item['chance'] for item in rare_and_above)
            total_common_chance = sum(item['chance'] for item in common_and_unusual)

            for item in rare_and_above:
                item['chance'] *= 2

            new_total_rare_chance = sum(item['chance'] for item in rare_and_above)
            adjustment = new_total_rare_chance - total_rare_chance

            adjustment_ratio = (total_common_chance - adjustment) / total_common_chance if total_common_chance > 0 else 0
            for item in common_and_unusual:
                item['chance'] *= adjustment_ratio

            modified_items = rare_and_above + common_and_unusual
        else:
            modified_items = current_case['items']

        total_chance = sum(item['chance'] for item in modified_items)

        if total_chance == 0:
            winning_item = current_case['items'][0]
        else:
            rand_text = requests.get('http://www.random.org/decimal-fractions/?num=1&dec=10&format=plain&rnd=new').text
            try:
                rand_num = total_chance * float(rand_text)
            except ValueError:
                import random
                rand_num = total_chance * random.random()

            winning_item = None
            current_chance = 0
            for item in modified_items:
                current_chance += item['chance']
                if rand_num < current_chance:
                    winning_item = item
                    break

        if not winning_item:
            winning_item = modified_items[-1]

        user_data['inventory'].append(winning_item)
        user_data['stats']['cases_opened'] += 1
        if winning_item.get('price') and (user_data['stats']['best_drop'] is None or winning_item['price'] > user_data['stats']['best_drop']['price']):
            user_data['stats']['best_drop'] = winning_item
        user_data['stats']['case_open_stats'][case_id] = user_data['stats']['case_open_stats'].get(case_id, 0) + 1

        all_data = load_data()
        all_data['users'][str(user_id)] = user_data
        save_data(all_data)

        return jsonify({"success": True, "winning_item": winning_item, "new_balance": user_data['balance']})
    except Exception as e:
        logger.error(f"Error in open_case: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/admin/give_balance', methods=['POST'])
def admin_give_balance():
    data = request.json
    admin_id = data.get('admin_id')
    user_id = data.get('user_id')
    amount = data.get('amount')

    if int(admin_id) != ADMIN_ID:
        return jsonify({"error": "Access denied"}), 403

    user_data = get_user(user_id)
    user_data['balance'] += int(amount)

    all_data = load_data()
    all_data['users'][str(user_id)] = user_data
    save_data(all_data)

    return jsonify({"success": True, "new_balance": user_data['balance']})

@app.route('/api/admin/set_flags', methods=['POST'])
def admin_set_flags():
    data = request.json
    admin_id = data.get('admin_id')
    flag = data.get('flag')
    value = data.get('value')

    if int(admin_id) != ADMIN_ID:
        return jsonify({"error": "Access denied"}), 403

    all_data = load_data()
    for key in all_data['flags']:
        all_data['flags'][key] = False

    if value == 'true':
        all_data['flags'][flag] = True

    save_data(all_data)

    return jsonify({"success": True, "flags": all_data['flags']})

@app.route('/api/admin/create_event', methods=['POST'])
def admin_create_event():
    data = request.json
    admin_id = data.get('admin_id')
    event_data = data.get('event_data')

    if int(admin_id) != ADMIN_ID:
        return jsonify({"error": "Access denied"}), 403

    all_data = load_data()
    all_data['event'] = event_data
    save_data(all_data)

    return jsonify({"success": True, "event": all_data['event']})

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[
        InlineKeyboardButton("Открыть сайт", web_app={"url": WEB_APP_URL})
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Нажмите кнопку ниже, чтобы открыть GiftRunner!",
        reply_markup=reply_markup
    )

def run_flask_app():
    app.run(host='0.0.0.0', port=5000) # ОСТАВЛЯЕМ КАК ТУТ, НИЧЕГО НЕ ТРОГАЕМ ЕСЛИ ПРОСТО ТЕСТИТЕ.

def main() -> None:
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start_command))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
