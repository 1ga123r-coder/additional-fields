import os
import time
import random
import requests
from flask import Flask, request, jsonify
from threading import Thread

# ========== НАСТРОЙКИ ==========
API_TOKEN = os.environ.get('USEDESK_API_TOKEN')
if not API_TOKEN:
    raise RuntimeError("Переменная окружения USEDESK_API_TOKEN не установлена!")

TICKET_UPDATE_URL = "https://secure.usedesk.ru/uapi/update/ticket"

# Диапазоны для поля 27363
RANGE_START = 33615443
RANGE_END = 33995640      # включительно
THRESHOLD_NEXT = 33995641 # начиная с этого значения – март

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def update_ticket_custom_field(ticket_id: int, field_id: int, value: str) -> bool:
    """Обновляет кастомное поле тикета через API UseDesk."""
    payload = {
        "api_token": API_TOKEN,
        "ticket_id": ticket_id,
        f"field_{field_id}": value
    }
    try:
        response = requests.post(TICKET_UPDATE_URL, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "success"
    except Exception as e:
        print(f"Ошибка обновления поля {field_id} тикета {ticket_id}: {e}")
        return False

def validate_email(email: str) -> bool:
    """
    Проверяет email через Rapid Email Validator.
    Возвращает True только для полностью валидных email.
    """
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
        # В случае сбоя считаем email валидным, чтобы не блокировать
        return True

def get_custom_field_value(ticket_data: dict, field_id: int):
    """
    Извлекает значение кастомного поля из массива custom_fields.
    Возвращает значение или None, если поле не найдено.
    """
    custom_fields = ticket_data.get('custom_fields', [])
    for field in custom_fields:
        if field.get('ticket_field_id') == field_id:
            return field.get('value')
    return None

def process_webhook(data: dict) -> None:
    """Фоновая обработка вебхука."""
    # Извлечение данных тикета
    if 'ticket' in data and isinstance(data['ticket'], dict):
        ticket_data = data['ticket']
    else:
        ticket_data = data

    ticket_id = ticket_data.get('id')
    if not ticket_id:
        print("В вебхуке нет id тикета")
        return

    # ---------- ПРОВЕРКА EMAIL ----------
    client_email = ticket_data.get('email')
    if client_email:
        print(f"Проверяем email {client_email} для тикета {ticket_id}...")
        if not validate_email(client_email):
            print(f"❌ Email невалиден. Обновляем поле 30668 = 1")
            update_ticket_custom_field(ticket_id, 30668, "1")
        else:
            print(f"✅ Email валиден, поле 30668 не меняем")
    else:
        print("В тикете нет email, проверка пропущена")

    # ---------- ОСНОВНАЯ ЛОГИКА С ПОЛЕМ 27363 ----------
    # Получаем значение поля 27363 из custom_fields
    value_27363 = get_custom_field_value(ticket_data, 27363)
    if value_27363 is None:
        print(f"Поле 27363 не найдено в custom_fields тикета {ticket_id}")
        return

    # Преобразуем в число
    try:
        num_value = int(value_27363)
    except (ValueError, TypeError):
        print(f"Значение поля 27363 не является числом: {value_27363}, пропускаем")
        return

    # Ожидание 10–20 секунд
    wait_seconds = random.randint(10, 20)
    print(f"Ожидание {wait_seconds} секунд перед проверкой тикета {ticket_id}...")
    time.sleep(wait_seconds)

    # Определяем новое значение для поля 30667
    if RANGE_START <= num_value <= RANGE_END:
        new_value = "февраль"
    elif num_value >= THRESHOLD_NEXT:
        new_value = "март"
    else:
        print(f"Значение {num_value} не попадает ни в один диапазон, тикет {ticket_id} пропускаем")
        return

    # Обновляем поле 30667
    success = update_ticket_custom_field(ticket_id, 30667, new_value)
    if success:
        print(f"✅ Тикет {ticket_id}: поле 30667 обновлено на '{new_value}'")
    else:
        print(f"❌ Тикет {ticket_id}: не удалось обновить поле 30667")

# ========== FLASK-ПРИЛОЖЕНИЕ ==========
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