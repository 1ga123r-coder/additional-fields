import os
import time
import random
import sys
import json
import requests
from flask import Flask, request, jsonify
from threading import Thread

# ========== НАСТРОЙКИ ==========
API_TOKEN = os.environ.get('USEDESK_API_TOKEN')
if not API_TOKEN:
    raise RuntimeError("Переменная окружения USEDESK_API_TOKEN не установлена!")

TICKET_UPDATE_URL = "https://api.usedesk.ru/update/ticket"  # официальный URL

# Диапазоны для поля 27363
RANGE_START = 33615443
RANGE_END = 33995640      # включительно
THRESHOLD_NEXT = 33995641 # начиная с этого значения – март

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def update_ticket_custom_field(ticket_id: int, field_id: int, value: str) -> bool:
    """
    Обновляет кастомное поле тикета через официальный API UseDesk.
    Использует параметры field_id и field_value.
    """
    payload = {
        "api_token": API_TOKEN,
        "ticket_id": ticket_id,
        "field_id": str(field_id),
        "field_value": value,
        "silent": "true"  # не менять статус тикета
    }
    try:
        response = requests.post(
            TICKET_UPDATE_URL,
            data=payload,  # важно: data, а не json
            timeout=10
        )
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "success"
    except Exception as e:
        print(f"Ошибка обновления поля {field_id} тикета {ticket_id}: {e}")
        sys.stdout.flush()
        return False

def validate_email(email: str) -> bool:
    """Проверяет email через Rapid Email Validator."""
    if not email:
        return False
    try:
        response = requests.get(
            "https://rapid-email-verifier.fly.dev/api/validate",
            params={"email": email},
            timeout=10
        )
        if response.status_code != 200:
            print(f"Rapid API вернул статус {response.status_code}")
            return False
        data = response.json()
        is_valid = data.get("status") == "VALID"
        if not is_valid:
            print(f"Email {email} невалиден: {data.get('status')}")
        return is_valid
    except Exception as e:
        print(f"Ошибка проверки email {email}: {e}")
        # В случае сбоя считаем email валидным
        return True

def get_custom_field_value(webhook_data: dict, field_id: int):
    """
    Возвращает значение кастомного поля по ticket_field_id.
    Ищет в webhook_data['custom_fields'] (верхний уровень).
    """
    custom_fields = webhook_data.get('custom_fields')
    if not custom_fields:
        return None
    for field in custom_fields:
        if field.get('ticket_field_id') == field_id:
            return field.get('value')
    return None

# ========== ОСНОВНАЯ ЛОГИКА ==========
def process_webhook(data: dict) -> None:
    """Фоновая обработка вебхука."""
    # Выводим полученные данные для отладки (можно убрать после наладки)
    data_preview = json.dumps(data, ensure_ascii=False)[:500]
    print(f"Получен вебхук: {data_preview}")
    sys.stdout.flush()

    # Извлечение данных тикета
    if 'ticket' in data and isinstance(data['ticket'], dict):
        ticket_data = data['ticket']
    else:
        ticket_data = data

    ticket_id = ticket_data.get('id')
    if not ticket_id:
        print("В вебхуке нет id тикета")
        sys.stdout.flush()
        return

    print(f"Обработка тикета {ticket_id}")
    sys.stdout.flush()

    # ---------- ПРОВЕРКА EMAIL ----------
    client_email = ticket_data.get('email')
    if client_email:
        print(f"Проверяем email {client_email} для тикета {ticket_id}...")
        sys.stdout.flush()
        if not validate_email(client_email):
            print(f"❌ Email невалиден. Обновляем поле 30668 = 1")
            update_ticket_custom_field(ticket_id, 30668, "1")
        else:
            print(f"✅ Email валиден, поле 30668 не меняем")
    else:
        print("В тикете нет email, проверка пропущена")
    sys.stdout.flush()

    # ---------- ОСНОВНАЯ ЛОГИКА С ПОЛЕМ 27363 ----------
    value_27363 = get_custom_field_value(data, 27363)
    if value_27363 is None:
        print(f"Поле 27363 не найдено в custom_fields тикета {ticket_id}")
        sys.stdout.flush()
        return

    try:
        num_value = int(value_27363)
        print(f"Значение поля 27363: {num_value}")
    except (ValueError, TypeError):
        print(f"Значение поля 27363 не является числом: {value_27363}, пропускаем")
        sys.stdout.flush()
        return

    # Ожидание 10–20 секунд
    wait_seconds = random.randint(10, 20)
    print(f"Ожидание {wait_seconds} секунд перед обновлением поля 30667...")
    sys.stdout.flush()
    time.sleep(wait_seconds)

    # Определяем новое значение для поля 30667
    if RANGE_START <= num_value <= RANGE_END:
        new_value = "февраль"
    elif num_value >= THRESHOLD_NEXT:
        new_value = "март"
    else:
        print(f"Значение {num_value} не попадает ни в один диапазон, тикет {ticket_id} пропускаем")
        sys.stdout.flush()
        return

    # Обновляем поле 30667
    success = update_ticket_custom_field(ticket_id, 30667, new_value)
    if success:
        print(f"✅ Тикет {ticket_id}: поле 30667 обновлено на '{new_value}'")
    else:
        print(f"❌ Тикет {ticket_id}: не удалось обновить поле 30667")
    sys.stdout.flush()

# ========== FLASK-ПРИЛОЖЕНИЕ ==========
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data"}), 400

    # Запускаем обработку в фоновом потоке
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