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

TICKET_UPDATE_URL = "https://api.usedesk.ru/update/ticket"
TICKET_GET_URL = "https://api.usedesk.ru/ticket"

# Диапазоны для поля 27363
RANGE_1_START = 34006983
RANGE_1_END = 34018112      # включительно -> значение "161741"
THRESHOLD = 34018113         # начиная с этого значения -> "164754"

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def update_ticket_custom_field(ticket_id: int, field_id: int, value: str) -> bool:
    """
    Обновляет кастомное поле тикета согласно официальной документации UseDesk.
    """
    payload = {
        "api_token": API_TOKEN,
        "ticket_id": ticket_id,
        "field_id": str(field_id),
        "field_value": value,
        "silent": "true"       # не менять статус тикета
    }
    try:
        response = requests.post(TICKET_UPDATE_URL, data=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "success"
    except Exception as e:
        print(f"Ошибка обновления поля {field_id} тикета {ticket_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Ответ сервера: {e.response.text}")
        sys.stdout.flush()
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
            sys.stdout.flush()
            return False
        data = response.json()
        is_valid = data.get("status") == "VALID"
        if not is_valid:
            print(f"Email {email} невалиден: {data.get('status')}")
            sys.stdout.flush()
        return is_valid
    except Exception as e:
        print(f"Ошибка проверки email {email}: {e}")
        sys.stdout.flush()
        # В случае сбоя считаем email валидным, чтобы не блокировать обработку
        return True

def get_ticket_details(ticket_id: int):
    """
    Получает полные данные тикета через API UseDesk.
    Возвращает словарь с данными тикета или None.
    """
    payload = {"api_token": API_TOKEN, "ticket_id": ticket_id}
    try:
        response = requests.post(TICKET_GET_URL, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Ошибка получения данных тикета {ticket_id}: {e}")
        return None

def get_custom_fields_from_ticket(ticket_id: int):
    """
    Пытается получить custom_fields из вебхука или через API.
    Возвращает список полей или None.
    """
    # Сначала пробуем получить через API (наиболее надёжно)
    ticket_data = get_ticket_details(ticket_id)
    if ticket_data and 'custom_fields' in ticket_data:
        return ticket_data['custom_fields']
    return None

# ========== ОСНОВНАЯ ЛОГИКА ОБРАБОТКИ ВЕБХУКА ==========
def process_webhook(data: dict) -> None:
    """Фоновая обработка вебхука."""
    # Логируем первые 1000 символов данных для диагностики
    data_preview = json.dumps(data, ensure_ascii=False)[:1000]
    print(f"=== ПОЛУЧЕН ВЕБХУК: {data_preview}")
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

    # ---------- ПОЛУЧЕНИЕ ПОЛЯ 27363 ----------
    # Сначала пробуем взять custom_fields из вебхука (верхний уровень)
    custom_fields = data.get('custom_fields')
    if not custom_fields:
        # Если нет в вебхуке, получаем через API
        print("custom_fields не найдены в вебхуке, запрашиваем через API...")
        custom_fields = get_custom_fields_from_ticket(ticket_id)
        if not custom_fields:
            print(f"Не удалось получить custom_fields для тикета {ticket_id}")
            sys.stdout.flush()
            return
        else:
            print("custom_fields получены через API")
    else:
        print("custom_fields найдены в вебхуке")

    print(f"Количество полей в custom_fields: {len(custom_fields)}")
    field_ids = [f.get('ticket_field_id') for f in custom_fields]
    print(f"Список ticket_field_id: {field_ids}")
    sys.stdout.flush()

    # Ищем поле 27363
    value_27363 = None
    for field in custom_fields:
        if field.get('ticket_field_id') == 27363:
            value_27363 = field.get('value')
            print(f"Найдено поле 27363 со значением: {value_27363}")
            break

    if value_27363 is None:
        print(f"Поле 27363 не найдено в custom_fields тикета {ticket_id}")
        sys.stdout.flush()
        return

    # Преобразуем в число
    try:
        num_value = int(value_27363)
        print(f"Числовое значение поля 27363: {num_value}")
    except (ValueError, TypeError):
        print(f"Значение поля 27363 не является числом: {value_27363}, пропускаем")
        sys.stdout.flush()
        return

    # Ожидание 10–20 секунд (может быть, нужно, чтобы поле 30187 стало доступно для обновления)
    wait_seconds = random.randint(10, 20)
    print(f"Ожидание {wait_seconds} секунд перед обновлением...")
    sys.stdout.flush()
    time.sleep(wait_seconds)

    # Определяем новое значение для поля 30187
    if RANGE_1_START <= num_value <= RANGE_1_END:
        new_value = "161741"
    elif num_value >= THRESHOLD:
        new_value = "164754"
    else:
        print(f"Значение {num_value} не попадает ни в один диапазон, тикет {ticket_id} пропускаем")
        sys.stdout.flush()
        return

    # Обновляем поле 30187
    success = update_ticket_custom_field(ticket_id, 30187, new_value)
    if success:
        print(f"✅ Тикет {ticket_id}: поле 30187 обновлено на '{new_value}'")
    else:
        print(f"❌ Тикет {ticket_id}: не удалось обновить поле 30187")
    sys.stdout.flush()

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