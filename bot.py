import io
import os
import re
import asyncio
import requests
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from PIL import Image, ImageDraw, ImageFont

# Получаем токен из переменных среды Render или задаем напрямую
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

QUEUE_KEYS = [
    "1.1", "1.2", "2.1", "2.2",
    "3.1", "3.2", "4.1", "4.2",
    "5.1", "5.2", "6.1", "6.2"
]

FONT_PATH = "Montserrat-Bold.ttf"

def ensure_font_exists():
    """Скачивает шрифт Montserrat с поддержкой кириллицы при первом старте."""
    if not os.path.exists(FONT_PATH):
        print("Завантаження шрифту Montserrat-Bold...")
        url = "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat-Bold.ttf"
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            with open(FONT_PATH, "wb") as f:
                f.write(r.content)
            print("Шрифт успішно завантажено!")
        except Exception as e:
            print(f"Помилка завантаження шрифту: {e}")

# Проверяем наличие шрифта до первого рендеринга
ensure_font_exists()

def get_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except IOError:
        return ImageFont.load_default()

def parse_kharkiv_post(text: str):
    """Парсит дату и все интервалы очередей из сообщения облэнерго."""
    text = text.replace('\xa0', ' ').replace('—', '-').replace('–', '-').replace('−', '-')

    # Поиск даты для подписи (например: 12 жовтня или понеділок, 12 жовтня)
    date_match = re.search(r'(?:у|в)?\s*([а-яіїєґ]+,?\s*\d{1,2}\s+[а-яіїєґ]+)', text, re.IGNORECASE)
    if date_match:
        caption_date = date_match.group(1).lower().replace(",", "")
    else:
        date_simple = re.search(r'(\d{1,2}\s+[а-яіїєґ]+)', text, re.IGNORECASE)
        caption_date = date_simple.group(1).lower() if date_simple else "сьогодні"

    schedule_header_date = caption_date.upper()

    schedule = {q: {"off": False, "intervals": []} for q in QUEUE_KEYS}
    lines = text.split("\n")

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        match_q = re.search(r'(?:^|[^\d])([1-6]\.[1-2])(?:\b|[:\s-])', line)
        if not match_q:
            continue

        q_key = match_q.group(1)
        content = line[match_q.end():].strip()

        if re.search(r'не\s*вимик|світло\s*є|немає\s*відключ|відсутні|^-$', content, re.IGNORECASE):
            schedule[q_key] = {"off": False, "intervals": []}
            continue

        matches = re.findall(r'(\d{1,2}[:.]\d{2})\s*(?:-|до)\s*(\d{1,2}[:.]\d{2})', content)
        if matches:
            intervals = [
                f"{start.replace('.', ':').zfill(5)} – {end.replace('.', ':').zfill(5)}"
                for start, end in matches
            ]
            schedule[q_key] = {"off": True, "intervals": intervals}
        else:
            schedule[q_key] = {"off": False, "intervals": []}

    return caption_date, schedule_header_date, schedule

def generate_schedule_image(schedule_date: str, schedule: dict) -> io.BytesIO:
    """Генерирует финальный постер 1080x1080 px без водяных знаков."""
    # Чистый желтый фон
    img = Image.new("RGBA", (1080, 1080), "#FFD200")
    draw = ImageDraw.Draw(img)

    # 1. Шапка
    draw.text((56, 60), "ХАРКІВОБЛЕНЕРГО • ОФІЦІЙНИЙ ГРАФІК", fill="#0F172A", font=get_font(16))
    draw.text((56, 86), "ВІДКЛЮЧЕННЯ СВІТЛА", fill="#0F172A", font=get_font(42))

    # Плашка с датой
    font_date = get_font(18)
    date_bbox = draw.textbbox((0, 0), schedule_date, font=font_date)
    date_w = date_bbox[2] - date_bbox[0] + 36
    badge_x = 1080 - 56 - date_w
    draw.rounded_rectangle([badge_x, 70, badge_x + date_w, 122], radius=14, fill="#0F172A")
    draw.text((badge_x + 18, 84), schedule_date, fill="#FFD200", font=font_date)

    # 2. Сетка карточек (4 строки x 3 колонки)
    grid_x = 56
    grid_y = 155
    total_w = 1080 - 112
    total_h = 1080 - 155 - 55
    cols = 3
    rows = 4
    gap_x = 18
    gap_y = 16
    card_w = (total_w - (cols - 1) * gap_x) / cols
    card_h = (total_h - (rows - 1) * gap_y) / rows

    for idx, q in enumerate(QUEUE_KEYS):
        c = idx % cols
        r = idx // cols
        x = grid_x + c * (card_w + gap_x)
        y = grid_y + r * (card_h + gap_y)
        item = schedule[q]

        if not item["off"] or len(item["intervals"]) == 0:
            # Карточка: Свет есть
            draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=20, fill="#FFFFFF")
            draw.text((x + 20, y + 16), f"ЧЕРГА {q}", fill="#0F172A", font=get_font(30))

            inner_y1 = y + 62
            inner_y2 = y + card_h - 18
            draw.rounded_rectangle([x + 18, inner_y1, x + card_w - 18, inner_y2], radius=14, fill="#ECFDF5")
            cx = x + card_w / 2
            cy = inner_y1 + (inner_y2 - inner_y1) / 2
            draw.text((cx, cy), "СВІТЛО Є", fill="#059669", font=get_font(21), anchor="mm")
        else:
            # Карточка: Отключение
            draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=20, fill="#0F172A")
            draw.text((x + 20, y + 15), f"ЧЕРГА {q}", fill="#FFFFFF", font=get_font(28))

            draw.rounded_rectangle([x + card_w - 74, y + 16, x + card_w - 18, y + 42], radius=8, fill="#DC2626")
            draw.text((x + card_w - 46, y + 29), "ВИМК", fill="#FFFFFF", font=get_font(12), anchor="mm")

            intervals = item["intervals"]
            count = len(intervals)
            content_y = y + 54
            content_h = card_h - 66

            if count == 1:
                slot_h, font_sz, gap = 52, 23, 0
            elif count == 2:
                slot_h, font_sz, gap = 40, 19, 10
            elif count == 3:
                slot_h, font_sz, gap = 34, 16, 6
            else:
                gap = 4
                slot_h = max(22, int((content_h - (count - 1) * gap) / count))
                font_sz = max(12, int(slot_h * 0.58))

            total_slots_h = count * slot_h + (count - 1) * gap
            start_y = content_y + max(0, (content_h - total_slots_h) / 2)

            font_time = get_font(font_sz)
            for t_idx, time_str in enumerate(intervals):
                sy = start_y + t_idx * (slot_h + gap)
                draw.rounded_rectangle([x + 14, sy, x + card_w - 14, sy + slot_h], radius=10, fill="#1E293B", outline="#334155", width=1)
                draw.text((x + card_w / 2, sy + slot_h / 2), time_str, fill="#FFD200", font=font_time, anchor="mm")

    output = io.BytesIO()
    img.convert("RGB").save(output, format="PNG", quality=95)
    output.seek(0)
    return output

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("⚡ Надішліть або перешліть сюди офіційне повідомлення обленерго з графіком.")

@dp.message(F.text)
async def process_schedule(message: types.Message):
    text = message.text
    if not re.search(r'[1-6]\.[1-2]', text):
        await message.answer("⚠️ У тексті не знайдено черг формату 1.1, 2.2 тощо.")
        return

    status_msg = await message.answer("⏳ Малюю графік...")
    try:
        caption_date, schedule_header_date, schedule = parse_kharkiv_post(text)
        image_stream = generate_schedule_image(schedule_header_date, schedule)

        # Формируем готовый пост с гиперссылкой в тексте https://svitlo-ua.info
        caption_text = (
            f"💡Графік відключень світла для Харківщини на {caption_date}.\n\n"
            f"Перелік адрес за чергами – <a href=\"https://t.me/kharkivenergy/1445\">тут</a>.\n\n"
            f"⚡️ Графіки відключення, оновлені черги, все про світло в Харкові та області тут ➡️ "
            f"<a href=\"https://t.me/+5FOhqtKOJxswYmZi\">https://svitlo-ua.info</a>"
        )

        photo = types.BufferedInputFile(image_stream.read(), filename="grafik.png")
        await message.answer_photo(
            photo=photo,
            caption=caption_text,
            parse_mode=ParseMode.HTML
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка: {e}")

# Web-сервер для прохождения проверки порта в Render
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_web_server()
    print("Web-сервер запущено. Бот готовий до роботи...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
