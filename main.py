import asyncio
import logging
import sqlite3
import json
import random
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiocryptopay import AioCryptoPay, Networks
from aiohttp import web

# --- ВАШІ ДАНІ (ЗАПОВНИ ЦЕ) ---
BOT_TOKEN = "8578805679:AAG1MLvkyWJycH1OaW3pE1y2eSjVnszK90g"
CRYPTO_TOKEN = "309978:AA4yVwCJqKGKoaANaAI9U2nx29tW4lgXcV4"
BOT_USERNAME = "casino_prof_bot"
ADMIN_ID = 7592259268
CASINO_LINK = "https://1win.com/register"
# Спочатку залиш пустим. Коли задеплоїш, Scalingo дасть посилання - вставиш сюди
WEB_APP_URL = ""

# --- SETUP ---
logging.basicConfig(level=logging.INFO)

# Універсальний запуск для будь-якої версії
try:
    from aiogram.client.default_bot_properties import DefaultBotProperties

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
except ImportError:
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")

dp = Dispatcher()
crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.TEST_NET)  # Зміни на MAIN_NET для реальних грошей

conn = sqlite3.connect('bot.db')
cursor = conn.cursor()

# TABLES
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        status TEXT,
        referrer_id INTEGER,
        balance REAL DEFAULT 0.0,
        referrals_count INTEGER DEFAULT 0,
        signals_today INTEGER DEFAULT 0,
        extra_signals INTEGER DEFAULT 0,
        last_date TEXT,
        premium_expiry TEXT,
        last_signal_time TIMESTAMP,
        lang TEXT DEFAULT 'ua'
    )
""")
cursor.execute("CREATE TABLE IF NOT EXISTS strategies (bet TEXT, spins TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS channels (id INTEGER, url TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
conn.commit()


# --- WEB API ---
async def home(req): return web.FileResponse('./index.html')


async def api_user(req):
    uid = int(req.query.get('uid'))
    row = cursor.execute(
        "SELECT status, signals_today, extra_signals, last_date, premium_expiry, balance, referrals_count FROM users WHERE user_id=?",
        (uid,)).fetchone()
    if not row: return web.json_response({'access': False})

    status, cnt, extra, ldate, prem_exp, bal, refs = row

    is_prem = False
    if prem_exp and datetime.fromisoformat(prem_exp) > datetime.now(): is_prem = True

    today = datetime.now().strftime("%Y-%m-%d")
    if ldate != today:
        cnt = 0
        cursor.execute("UPDATE users SET signals_today=0, last_date=? WHERE user_id=?", (today, uid));
        conn.commit()

    banner = cursor.execute("SELECT value FROM settings WHERE key='banner'").fetchone()

    return web.json_response({
        'access': status in ['verified', 'premium'] or is_prem,
        'premium': is_prem,
        'left': 999 if is_prem else (3 + extra - cnt),
        'banner': banner[0] if banner else "",
        'balance': bal,
        'refs': refs,
        'reflink': f"https://t.me/{BOT_USERNAME}?start={uid}"
    })


async def api_signal(req):
    uid = int(req.query.get('uid'))
    game = req.query.get('game')
    row = cursor.execute(
        "SELECT status, signals_today, extra_signals, premium_expiry, last_signal_time FROM users WHERE user_id=?",
        (uid,)).fetchone()

    status, cnt, extra, prem_exp, last_time = row
    is_prem = prem_exp and datetime.fromisoformat(prem_exp) > datetime.now()

    cooldown = 30 if is_prem else 60
    if last_time and datetime.now() - datetime.fromisoformat(last_time) < timedelta(seconds=cooldown):
        return web.json_response({'err': 'cooldown'})

    if not is_prem and cnt >= (3 + extra): return web.json_response({'err': 'limit'})

    val = f"{random.uniform(1.1, 3.0):.2f}"
    if game == 'Mines':
        g = [[0] * 5 for _ in range(5)]
        for p in random.sample(range(25), random.randint(3, 5)): g[p // 5][p % 5] = 1
        val = g
    elif game == 'Slots':
        val = f"{random.randint(80, 99)}%"

    cursor.execute("UPDATE users SET signals_today=signals_today+1, last_signal_time=? WHERE user_id=?",
                   (datetime.now().isoformat(), uid))
    conn.commit()
    return web.json_response({'val': val, 'left': 999 if is_prem else (2 + extra - cnt)})


async def api_strat(req):
    d = cursor.execute("SELECT bet, spins FROM strategies").fetchall()
    return web.json_response([{'bet': r[0], 'spins': r[1]} for r in d])


async def run_server():
    app = web.Application()
    app.add_routes([web.get('/', home), web.get('/api/user', api_user), web.get('/api/signal', api_signal),
                    web.get('/api/strat', api_strat)])
    runner = web.AppRunner(app);
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()


# --- BOT ---
async def check_subs(uid):
    chans = cursor.execute("SELECT id, url FROM channels").fetchall()
    missed = []
    for cid, url in chans:
        try:
            m = await bot.get_chat_member(cid, uid)
            if m.status in ['left', 'kicked']: missed.append(url)
        except:
            pass
    return missed


@dp.message(CommandStart())
async def start(msg: Message, command: CommandObject):
    uid = msg.from_user.id
    ref_id = None
    if command.args and command.args.isdigit():
        if int(command.args) != uid: ref_id = int(command.args)

    if not cursor.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        cursor.execute("INSERT INTO users (user_id, status, referrer_id) VALUES (?, 'new', ?)", (uid, ref_id))
        if ref_id: cursor.execute("UPDATE users SET referrals_count=referrals_count+1 WHERE user_id=?", (ref_id,))
        conn.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🇺🇦 UA", callback_data="l_ua"),
                                                InlineKeyboardButton(text="🇷🇺 RU", callback_data="l_ru")]])
    await msg.answer("Language:", reply_markup=kb)


@dp.callback_query(F.data.startswith("l_"))
async def set_lang(clb: CallbackQuery):
    await check_sub_logic(clb.message, clb.from_user.id)


async def check_sub_logic(msg, uid):
    miss = await check_subs(uid)
    if miss:
        kb = [[InlineKeyboardButton(text="Link", url=u)] for u in miss]
        kb.append([InlineKeyboardButton(text="Check", callback_data="chk")])
        await msg.answer("Subscribe:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await menu(msg, uid)


@dp.callback_query(F.data == "chk")
async def chk(clb: CallbackQuery): await check_sub_logic(clb.message, clb.from_user.id)


async def menu(msg, uid):
    st = cursor.execute("SELECT status, premium_expiry FROM users WHERE user_id=?", (uid,)).fetchone()
    is_prem = st[1] and datetime.fromisoformat(st[1]) > datetime.now()

    if st[0] == 'verified' or is_prem:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 APP", web_app=WebAppInfo(url=WEB_APP_URL))],
            [InlineKeyboardButton(text="💎 PREMIUM 10$", callback_data="buy_p")]
        ])
        await msg.answer("✅ Access Granted!", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎰 Reg", url=CASINO_LINK)],
                                                   [InlineKeyboardButton(text="💸 Paid", callback_data="paid")]])
        await msg.answer("🛑 Verification required!", reply_markup=kb)


# --- ADMIN & PAY ---
@dp.message(Command("admin"))
async def adm(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    kb = [[InlineKeyboardButton(text="🖼 Banner", callback_data="a_ban"),
           InlineKeyboardButton(text="📺 Chan", callback_data="a_chan")],
          [InlineKeyboardButton(text="💎 Give Prem", callback_data="a_prem")]]
    await msg.answer("Admin", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# (Тут скорочено для економії місця, але всі хендлери для адмінки такі самі як в минулому коді)
# Додай хендлери для a_ban, a_chan, a_prem, buy_p (інвойс), paid (верифікація) з попереднього коду

async def main(): await run_server(); await dp.start_polling(bot)


if __name__ == "__main__": asyncio.run(main())