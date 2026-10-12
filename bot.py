import io
import math
import os
import re
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from PIL import Image, ImageDraw, ImageFont

# Отримуємо токен зі змінних середовища Render або використовуємо дефолтний
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТОКЕН_БОТА")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

QUEUE_KEYS = [
    "1.1", "1.2", "2.1", "2.2",
    "3.1", "3.2", "4.1", "4.2",
    "5.1", "5.2", "6.1", "6.2"
]

FONT_PATH = "fonts/Montserrat-Bold.ttf"

def get_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except IOError:
        return ImageFont.load_default()

def parse_kharkiv_post(text: str):
    date_match = re.search(r'(?:у|в)?\s*([а-яіїєґ]+,?\s*\d{1,2}\s+[а-яіїєґ]+)', text, re.IGNORECASE)
    if date_match:
        schedule_date = date_match.group(1).upper().replace(",", "")
    else:
        date_simple = re.search(r'(\d{1,2}\s+[а-яіїєґ]+)', text, re.IGNORECASE)
        schedule_date = date_simple.group(1).upper() if date_simple else "НА СЬОГОДНІ"

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

        if re.search(r'не\s*вимик|світло\s*є|немає\s*відключ|відсутні|-', content, re.IGNORECASE):
            schedule[q_key] = {"off": False, "intervals": []}
            continue

        matches = re.findall(r'(\d{1,2}[:.]\d{2})\s*(?:-|–|—|до)\s*(\d{1,2}[:.]\d{2})', content)
        if matches:
            intervals = [
                f"{start.replace('.', ':').zfill(5)} – {end.replace('.', ':').zfill(5)}"
                for start, end in matches
            ]
            schedule[q_key] = {"off": True, "intervals": intervals}
        else:
            schedule[q_key] = {"off": False, "intervals": []}

    return schedule_date, schedule

def draw_watermark(img: Image.Image):
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw_ov = ImageDraw.Draw(overlay)
    font_wm = get_font(32)

    word = "ТРУХА"
    step_x = 180
    step_y = 70
    amplitude = 14

    for y in range(-300, 1400, step_y):
        for x in range(-300, 1400, step_x):
            offset_y = math.sin((x + y * 0.5) / 120.0) * amplitude
            draw_ov.text((x, y + offset_y), word, fill=(15, 23, 42, 102), font=font_wm, anchor="mm")

    rotated_overlay = overlay.rotate(-25, resample=Image.Resampling.BICUBIC, center=(540, 540))
    img.alpha_composite(rotated_overlay)

def generate_schedule_image(schedule_date: str, schedule: dict) -> io.BytesIO:
    img = Image.new("RGBA", (1080, 1080), "#FFD200")
    draw_watermark(img)
    draw = ImageDraw.Draw(img)

    draw.text((56, 60), "ХАРКІВОБЛЕНЕРГО • ОФІЦІЙНИЙ ГРАФІК", fill="#0F172A", font=get_font(16))
    draw.text((56, 86), "ВІДКЛЮЧЕННЯ СВІТЛА", fill="#0F172A", font=get_font(42))

    font_date = get_font(18)
    date_bbox = draw.textbbox((0, 0), schedule_date, font=font_date)
    date_w = date_bbox[2] - date_bbox[0] + 36
    badge_x = 1080 - 56 - date_w
    draw.rounded_rectangle([badge_x, 70, badge_x + date_w, 122], radius=14, fill="#0F172A")
    draw.text((badge_x + 18, 84), schedule_date, fill="#FFD200", font=font_date)

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
            draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=20, fill="#FFFFFF")
            draw.text((x + 20, y + 16), f"ЧЕРГА {q}", fill="#0F172A", font=get_font(30))

            inner_y1 = y + 62
            inner_y2 = y + card_h - 18
            draw.rounded_rectangle([x + 18, inner_y1, x + card_w - 18, inner_y2], radius=14, fill="#ECFDF5")
            cx = x + card_w / 2
            cy = inner_y1 + (inner_y2 - inner_y1) / 2
            draw.text((cx, cy), "СВІТЛО Є", fill="#059669", font=get_font(21), anchor="mm")
        else:
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
        await message.answer("⚠️ У тексті не знайдено підчерг (наприклад, 1.1, 2.2).")
        return

    status_msg = await message.answer("⏳ Малюю графік...")
    try:
        schedule_date, schedule = parse_kharkiv_post(text)
        image_stream = generate_schedule_image(schedule_date, schedule)
        photo = types.BufferedInputFile(image_stream.read(), filename="grafik.png")
        await message.answer_photo(photo=photo, caption=f"⚡ {schedule_date}")
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка: {e}")

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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
