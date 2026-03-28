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

# URL для обновления тикета (используется тот же, что в исходном коде)
TICKET_UPDATE_URL = "https://secure.usedesk.ru/uapi/update/ticket"

# Диапазоны
RANGE_START = 33615443
RANGE_END = 33995640      # включительно
THRESHOLD_NEXT = 33995641 # начиная с этого значения – март

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def update_ticket_custom_field(ticket_id: int, field_id: int, value: str) -> bool:
    """
    Обновляет кастомное поле тикета через API UseDesk.
    Параметры: ticket_id, field_id, новое значение.
    Возвращает True при успехе.
    """
    payload = {
        "api_token": API_TOKEN,
        "ticket_id": ticket_id,
        f"field_{field_id}": value
    }
    try:
        response = requests.post(TICKET_UPDATE_URL, json=payload)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "success"
    except Exception as e:
        print(f"Ошибка обновления поля {field_id} тикета {ticket_id}: {e}")
        return False

def process_webhook(data: dict) -> None:
    """
    Фоновая обработка вебхука:
    - извлекает данные тикета,
    - ждёт 10–20 секунд,
    - проверяет поле 27363,
    - при необходимости обновляет поле 30667.
    """
    # Извлечение данных тикета
    if 'ticket' in data and isinstance(data['ticket'], dict):
        ticket_data = data['ticket']
    else:
        # Если структура иная (например, тикет передан напрямую)
        ticket_data = data

    ticket_id = ticket_data.get('id')
    if not ticket_id:
        print("В вебхуке нет id тикета")
        return

    # Получение кастомных полей
    ticket_fields = ticket_data.get('ticket_fields', [])
    if not ticket_fields:
        print(f"В тикете {ticket_id} нет кастомных полей")
        return

    # Ищем поле с id 27363
    field_27363 = None
    for field in ticket_fields:
        if field.get('id') == 27363:
            field_27363 = field
            break

    if not field_27363:
        print(f"Поле 27363 не найдено в тикете {ticket_id}")
        return

    value = field_27363.get('value')
    if value is None:
        print(f"Поле 27363 имеет значение null, тикет {ticket_id} пропускаем")
        return

    # Преобразуем value в число, если это возможно
    try:
        num_value = int(value)
    except (ValueError, TypeError):
        print(f"Значение поля 27363 не является числом: {value}, пропускаем")
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

    # Запускаем обработку в фоновом потоке, чтобы не задерживать ответ
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