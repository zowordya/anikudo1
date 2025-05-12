import flet as ft
import asyncio
import sqlite3
import logging
import os
import httpx
from dotenv import load_dotenv
from bs4 import BeautifulSoup

from aiogram import Bot, Dispatcher, types
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from g4f.client import Client

# === DATABASE ===
DB_NAME = "anime_plan.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plan (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                title TEXT,
                watched INTEGER DEFAULT 0,
                UNIQUE(user_id, title)
            )
        """)

def add_anime_to_plan(user_id, title):
    with sqlite3.connect(DB_NAME) as conn:
        try:
            conn.execute("INSERT INTO plan (user_id, title) VALUES (?, ?)", (user_id, title))
            conn.commit()
        except sqlite3.IntegrityError:
            pass

def remove_anime_from_plan(user_id, title):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM plan WHERE user_id = ? AND title = ?", (user_id, title))
        conn.commit()

def toggle_watched_status(user_id, title):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE plan SET watched = 1 - watched WHERE user_id = ? AND title = ?", (user_id, title))
        conn.commit()

def get_plan_list(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT title, watched FROM plan WHERE user_id = ?", (user_id,))
        return cursor.fetchall()

# === API FUNCTIONS ===
BASE_URL = "https://shikimori.one/api"  # Было с пробелом в конце
HEADERS = {"User-Agent": "AnimeViewerApp/1.0"}

async def search_anime_shikimori(query):
    async with httpx.AsyncClient(headers=HEADERS) as client:
        r = await client.get(f"{BASE_URL}/animes", params={"search": query})
        r.raise_for_status()
        results = r.json()
        if not results:
            return None
        anime = results[0]
        return {
            "title": anime.get("russian") or anime["name"],
            "episodes": anime["episodes"],
            "status": anime["status"],
            "score": anime["score"],
            "url": f"https://shikimori.one/animes/{anime['id']}-{anime['name']}"
        }

import httpx

async def get_seasonal_anime():
    url = "https://shikimori.one/api/animes"
    params = {
        "season": "spring_2025",  # формат: "season_year"
        "limit": 10,              # можно задать количество
        "order": "ranked"
    }

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        print("REST Response:", data)  # отладка

        return data


async def get_news():
    async with httpx.AsyncClient() as client:
        r = await client.get("https://shikimori.one/forum/news")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        return [item.text.strip() for item in soup.select(".b-news-topic__title")[:10]]

client = Client()

def generate_anime_description(title):
    prompt = f"Расскажи краткое описание аниме {title}."
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Ошибка генерации описания: {e}"

# === FLET APP ===
async def main(page: ft.Page):
    init_db()
    page.title = "Anime Viewer"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.AUTO

    tg_user = page.route.split("user_id=")[-1] if "user_id=" in page.route else "guest"
    try:
        user_id = int(tg_user)
    except ValueError:
        user_id = 0

    search_field = ft.TextField(label="Поиск аниме", width=400)
    anime_info = ft.Text()
    anime_desc = ft.Text()

    plan_list = ft.ListView(expand=1, spacing=10, padding=10)
    news_list = ft.ListView(expand=1, spacing=10, padding=10)
    seasonal_list = ft.ListView(expand=1, spacing=10, padding=10)

    async def search_anime(e):
        query = search_field.value.strip()
        result = await search_anime_shikimori(query)
        if result:
            anime_info.value = f"Название: {result['title']}\nЭпизодов: {result['episodes']}\nСтатус: {result['status']}\nОценка: {result['score']}\nСсылка: {result['url']}"
            anime_desc.value = generate_anime_description(result['title'])
        else:
            anime_info.value = "Аниме не найдено."
            anime_desc.value = ""
        await page.update()

    def add_to_plan(e):
        title = search_field.value.strip()
        if title:
            add_anime_to_plan(user_id, title)
            asyncio.create_task(load_plan())

    def remove_from_plan(e):
        title = e.control.data
        remove_anime_from_plan(user_id, title)
        asyncio.create_task(load_plan())

    def toggle_watched(e):
        title = e.control.data
        toggle_watched_status(user_id, title)
        asyncio.create_task(load_plan())

    async def load_plan():
        plan_list.controls.clear()
        for title, watched in get_plan_list(user_id):
            plan_list.controls.append(
                ft.Row([
                    ft.Checkbox(label=title, value=bool(watched), on_change=toggle_watched, data=title, expand=1),
                    ft.IconButton(icon=ft.icons.DELETE, tooltip="Удалить", on_click=remove_from_plan, data=title)
                ])
            )
        await page.update()

    async def load_news():
        news_list.controls.clear()
        for item in await get_news():
            news_list.controls.append(ft.Text(item))

    async def load_seasonal():
        seasonal_list.controls.clear()
        for item in await get_seasonal_anime():
            seasonal_list.controls.append(ft.Text(item))

    await load_news()
    await load_seasonal()
    await load_plan()

    tab_search = ft.Column([
        ft.Text("Поиск аниме", style="headlineSmall"),
        search_field,
        ft.Row([
            ft.ElevatedButton("Поиск", on_click=lambda e: asyncio.create_task(search_anime(e))),
            ft.ElevatedButton("Добавить в план", on_click=add_to_plan),
        ]),
        anime_info,
        anime_desc
    ])

    tab_plan = ft.Column([
        ft.Text("Запланированные аниме", style="headlineSmall"),
        plan_list
    ])

    tab_news = ft.Column([
        ft.Text("Новости аниме", style="headlineSmall"),
        news_list
    ])

    tab_season = ft.Column([
        ft.Text("Новинки сезона", style="headlineSmall"),
        seasonal_list
    ])

    page.add(
        ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Поиск", content=tab_search),
                ft.Tab(text="План", content=tab_plan),
                ft.Tab(text="Новинки", content=tab_season),
                ft.Tab(text="Новости", content=tab_news)
            ]
        )
    )

# === TELEGRAM BOT ===
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    webapp_url = f"https://anikudo1-git-main-sakutos-projects.vercel.app//user_id={message.from_user.id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть Anime WebApp", web_app=WebAppInfo(url=webapp_url))]
    ])
    await message.answer("👋 Привет! Вот твое приложение для аниме:", reply_markup=keyboard)

# === RUN BOT AND APP ===
async def run_all():
    bot_task = asyncio.create_task(dp.start_polling(bot))
    app_task = asyncio.create_task(ft.app_async(target=main, view=ft.WEB_BROWSER, port=8550))
    await asyncio.gather(bot_task, app_task)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_all())
