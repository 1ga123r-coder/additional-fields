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

TICKET_UPDATE_URL = "https://api.usedesk.ru/update/ticket"  # документированный эндпоинт
TICKET_GET_URL = "https://api.usedesk.ru/ticket"            # эндпоинт для получения тикета

# Диапазоны для поля 27363
RANGE_START = 33615443
RANGE_END = 33995640          # включительно
THRESHOLD_NEXT = 33995641     # начиная с этого значения – март

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def update_ticket_custom_field(ticket_id: int, field_id: int, value: str) -> bool:
    """Обновляет кастомное поле тикета согласно официальной документации UseDesk."""
    payload = {
        "api_token": API_TOKEN,
        "ticket_id": ticket_id,
        "field_id": str(field_id),
        "field_value": value,
        "silent": "true"
    }
    try:
        response = requests.post(TICKET_UPDATE_URL, data=payload, timeout=10)
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
        return True  # при сбое считаем валидным

def get_ticket_details(ticket_id: int):
    """Получает полные данные тикета через API UseDesk."""
    payload = {"api_token": API_TOKEN, "ticket_id": ticket_id}
    try:
        response = requests.post(TICKET_GET_URL, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"Ошибка получения данных тикета {ticket_id}: {e}")
        sys.stdout.flush()
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
    # Сначала пробуем найти в вебхуке
    custom_fields = data.get('custom_fields')
    if not custom_fields:
        custom_fields = data.get('ticket', {}).get('custom_fields')

    value_27363 = None
    if custom_fields:
        print("custom_fields найдены в вебхуке")
        for field in custom_fields:
            if field.get('ticket_field_id') == 27363:
                value_27363 = field.get('value')
                print(f"Найдено поле 27363 в вебхуке: {value_27363}")
                break
        sys.stdout.flush()

    # Если в вебхуке нет, ждём и запрашиваем через API
    if value_27363 is None:
        print("Поле 27363 не найдено в вебхуке, ждём 10-20 секунд и запрашиваем через API...")
        sys.stdout.flush()
        wait_seconds = random.randint(10, 20)
        print(f"Ожидание {wait_seconds} секунд...")
        sys.stdout.flush()
        time.sleep(wait_seconds)

        ticket_details = get_ticket_details(ticket_id)
        if not ticket_details:
            print(f"Не удалось получить данные тикета {ticket_id} через API")
            sys.stdout.flush()
            return

        # Извлекаем custom_fields из ответа API
        # В ответе API поля могут быть в разных местах: ticket.custom_fields или просто custom_fields
        api_custom_fields = ticket_details.get('custom_fields')
        if not api_custom_fields:
            api_custom_fields = ticket_details.get('ticket', {}).get('custom_fields')

        if api_custom_fields:
            for field in api_custom_fields:
                if field.get('ticket_field_id') == 27363:
                    value_27363 = field.get('value')
                    print(f"Найдено поле 27363 через API: {value_27363}")
                    break

    if value_27363 is None:
        print(f"Поле 27363 не найдено ни в вебхуке, ни через API. Тикет {ticket_id} пропускаем")
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

    # Ожидание (если уже ждали, не ждём повторно) – но мы уже ждали в блоке выше,
    # если не нашли в вебхуке. Если нашли в вебхуке, то ждём сейчас.
    if 'wait_seconds' not in locals():
        wait_seconds = random.randint(10, 20)
        print(f"Ожидание {wait_seconds} секунд перед обновлением...")
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