import os
import sys
import time
import random
import requests
from flask import Flask, request, jsonify
from threading import Thread

# ========== НАСТРОЙКИ ==========
API_TOKEN = os.environ.get('USEDESK_API_TOKEN')
if not API_TOKEN:
    raise RuntimeError("Переменная окружения USEDESK_API_TOKEN не установлена!")

TICKET_GET_URL = "https://api.usedesk.ru/ticket"
TICKET_UPDATE_URL = "https://secure.usedesk.ru/uapi/update/ticket"

ERROR_TAG = "testerrormail"

# Минимальная и максимальная задержка перед проверкой (в секундах)
MIN_DELAY = 60
MAX_DELAY = 120

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_ticket_details(ticket_id: int):
    """Получает полные данные тикета через API UseDesk."""
    payload = {"api_token": API_TOKEN, "ticket_id": ticket_id}
    try:
        response = requests.post(TICKET_GET_URL, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка получения данных тикета {ticket_id}: {e}")
        sys.stdout.flush()
        return None

def add_tag_to_ticket(ticket_id: int, tag: str) -> bool:
    """Добавляет тег к тикету через эндпоинт /uapi/update/ticket."""
    payload = {
        "api_token": API_TOKEN,
        "ticket_id": ticket_id,
        "tag": tag
    }
    try:
        response = requests.post(TICKET_UPDATE_URL, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "success"
    except Exception as e:
        print(f"Ошибка при добавлении тега {tag} к тикету {ticket_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Ответ сервера: {e.response.text}")
        sys.stdout.flush()
        return False

def check_comments_for_trigger_error(ticket_data: dict) -> bool:
    """Проверяет, есть ли в комментариях тикета комментарий с from='trigger' и type='error'."""
    comments = ticket_data.get("comments", [])
    for comment in comments:
        if comment.get("from") == "trigger" and comment.get("type") == "error":
            return True
    return False

# ========== ОСНОВНАЯ ЛОГИКА ==========
def process_webhook(data: dict) -> None:
    """Фоновая обработка вебхука с задержкой перед проверкой."""
    print(f"=== ПОЛУЧЕН ВЕБХУК: {data}")
    sys.stdout.flush()

    # Извлекаем ID тикета
    if 'ticket' in data and isinstance(data['ticket'], dict):
        ticket_data = data['ticket']
    else:
        ticket_data = data

    ticket_id = ticket_data.get('id')
    if not ticket_id:
        print("В вебхуке нет id тикета")
        sys.stdout.flush()
        return

    print(f"Тикет {ticket_id} получен. Ожидание {MIN_DELAY}-{MAX_DELAY} секунд перед проверкой...")
    delay = random.randint(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)
    print(f"Задержка завершена. Проверяем тикет {ticket_id}...")
    sys.stdout.flush()

    # Получаем полные данные тикета (включая комментарии)
    full_ticket = get_ticket_details(ticket_id)
    if not full_ticket:
        print(f"Не удалось получить данные тикета {ticket_id}")
        sys.stdout.flush()
        return

    # Проверяем наличие ошибки от триггера
    if check_comments_for_trigger_error(full_ticket):
        print(f"Найден комментарий с from='trigger' и type='error'. Добавляем тег {ERROR_TAG}...")
        success = add_tag_to_ticket(ticket_id, ERROR_TAG)
        if success:
            print(f"✅ Тикет {ticket_id}: тег {ERROR_TAG} успешно добавлен")
        else:
            print(f"❌ Тикет {ticket_id}: не удалось добавить тег {ERROR_TAG}")
    else:
        print(f"ℹ️ Тикет {ticket_id}: комментариев с trigger/error не найдено")

    sys.stdout.flush()

# ========== FLASK ==========
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data"}), 400
    thread = Thread(target=process_webhook, args=(data,))
    thread.daemon = True
    thread.start()
    return jsonify({"status": "accepted"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)