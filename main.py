import logging
import asyncio
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, ReplyKeyboardRemove
)
from db import get_all_user_ids  # db.py dan import qilamiz
from db import add_user
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, Mapped, mapped_column
from sqlalchemy import Column, Integer, String, Text, select, update, Float
import sqlite3
import logging
import os
from dotenv import load_dotenv

load_dotenv()


conn = sqlite3.connect('skins.db')
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS skins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    item TEXT,
    name TEXT,
    condition TEXT,
    price INTEGER,
    img TEXT
)
""")
conn.commit()
conn.close()


API_TOKEN = os.getenv('API_TOKEN')
SUPER_ADMIN_ID = int(os.getenv('SUPER_ADMIN_ID'))
ADMIN_IDS = [int(i) for i in os.getenv('ADMIN_IDS', '').split(',') if i]
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///skins.db')

Base = declarative_base()

auction_state = {
    "active": False,
    "photo_id": None,
    "end_time": None,
    "start_price": None,
    "step": None,
    "current_price": None,
    "leader_id": None,
    "leader_name": None,
    "bids": []
}
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

class Skin(Base):
    __tablename__ = "skins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(50))
    item: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    status = Column(String, default="pending")
    condition: Mapped[str] = mapped_column(String(50))
    price: Mapped[float] = mapped_column(Float)
    img: Mapped[str] = mapped_column(Text)


class Inventory(Base):
    __tablename__ = "inventories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    skin_id: Mapped[int] = mapped_column(Integer)
    
# --- FSM STATE DEPOSIT ---
class DepositFSM(StatesGroup):
    wait_amount = State()
    wait_method = State()
    wait_card_number = State()
    wait_screenshot = State()
    
class SellRequest(Base):
    __tablename__ = "sell_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    condition: Mapped[str] = mapped_column(String(50))
    price: Mapped[float] = mapped_column(Float)
    img: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # pending/confirmed/cancelled

class BuyRequest(Base):
    __tablename__ = "buy_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    skin_id: Mapped[int] = mapped_column(Integer)
    photo_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # pending/confirmed/cancelled

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    balance: Mapped[float] = mapped_column(Float, default=0)
    trade_link: Mapped[str] = mapped_column(Text, default="")

class AdminAction(Base):
    __tablename__ = "admin_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(50))  # sold, bought, added
    target_user: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(50))

class Auction(Base):
    __tablename__ = "auctions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skin_img: Mapped[str] = mapped_column(Text)
    start_time: Mapped[str] = mapped_column(String(50))
    end_time: Mapped[str] = mapped_column(String(50))
    start_price: Mapped[float] = mapped_column(Float)
    step: Mapped[float] = mapped_column(Float)
    current_price: Mapped[float] = mapped_column(Float)
    current_winner: Mapped[int] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, active, finished

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)



async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def add_user_balance(user_id: int, amount: float):
    # Bu yerda user_id balansini yangilash yoki xabar yuborish
    await bot.send_message(user_id, f"✅ P2P orqali {amount:,.0f} so'm depozit muvaffaqiyatli to‘ldirildi!")
    
async def get_or_create_user(user_id):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(id=user_id, balance=0.0, trade_link="")
            session.add(user)
            await session.commit()
        return user
    
# ---- FSM STATES ----
class BuySkin(StatesGroup):
    category = State()
    item = State()
    select_skin = State()
    confirm = State()

class SellSkin(StatesGroup):
    name = State()
    condition = State()
    photo = State()
    price = State()
    confirm = State()

class InventoryFSM(StatesGroup):
    wait_trade_url = State()

class AddSkin(StatesGroup):
    category = State()
    item = State()
    name = State()
    condition = State()
    price = State()
    img = State()
    confirm = State()

class DeleteSkinFSM(StatesGroup):
    waiting_item_name = State()
    waiting_skin_select = State()
    confirm = State()

class AdminManageFSM(StatesGroup):
    add_admin_id = State()
    remove_admin_id = State()

class AuctionFSM(StatesGroup):
    wait_img = State()
    wait_name = State()
    wait_time = State()
    wait_start_price = State()
    wait_step = State()
    confirm = State()



# ---- STATIC DATA ----
SKIN_CATEGORIES = {
    "Pichoqlar": ["Karambit", "Bayonet", "Butterfly"],
    "Pistoletlar": ["P2000", "USP-S", "Glock-18"],
    "Avtomatlar": ["AK-47", "M4A4", "M4A1-S"],
    "Vintovkalar": ["AWP", "SSG 08", "SCAR-20"],
    "Aksessuarlar": ["Agent", "Graffiti", "Sticker"]
}

# --- AUCTION STATE ---
auction_state = {
    "active": False,
    "https_img": None,
    "end_time": None,
    "name": None,
    "start_price": None,
    "step": None,
    "current_price": None,
    "leader_id": None,
    "leader_name": None,
    "bids": [],
    "rejalashtirildi": False,
    "started": False
}

# --- KEYBOARDS ---
def get_main_menu(user_id):
    rows = [
        [KeyboardButton(text="Profil")],
        [KeyboardButton(text="Skin olish"), KeyboardButton(text="Skin sotish")],
        [KeyboardButton(text="Inventar")],
        [KeyboardButton(text="Auksion")]
    ]
    if user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text="Admin panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_profile_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Trade silkam"), KeyboardButton(text="Balansim")],
            [KeyboardButton(text="Depozit"), KeyboardButton(text="⬅️ Orqaga")]
        ],
        resize_keyboard=True
    )

def get_category_kb():
    rows = [[KeyboardButton(text=cat)] for cat in SKIN_CATEGORIES]
    rows.append([KeyboardButton(text="⬅️ Orqaga")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_items_kb(category):
    rows = [[KeyboardButton(text=item)] for item in SKIN_CATEGORIES.get(category, [])]
    rows.append([KeyboardButton(text="⬅️ Orqaga")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_inventory_kb():
    rows = [
        [KeyboardButton(text="Trade silka biriktirish")],
        [KeyboardButton(text="Skinlarim")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_skin_action_kb():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Steamga chiqarish", callback_data="withdraw_skin")],
            [InlineKeyboardButton(text="Skinni sotish", callback_data="sell_my_skin")]
        ]
    )
    return kb

def get_admin_panel_kb(user_id):
    rows = [
        [KeyboardButton(text="Skin qo'shish")],
        [KeyboardButton(text="Skin o'chirish")],  # <<=== yangi tugma
    ]
    if user_id == SUPER_ADMIN_ID or user_id in ADMIN_IDS:
        rows.append([KeyboardButton(text="Depozit zayafkalari")])
    rows.extend([
        [KeyboardButton(text="Sotish zayafkalari")],
        [KeyboardButton(text="Botni boshqarish")],
        [KeyboardButton(text="Auksion boshqarish")],
        [KeyboardButton(text="Adminlarni boshqarish")],
        [KeyboardButton(text="⬅️ Orqaga")]
    ])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def get_auction_kb():
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Auksionda ishtirok etish", callback_data="join_auction")]
        ]
    )
    return kb
def get_all_user_ids():
    conn = sqlite3.connect("user.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row[0] for row in rows]

def get_auction_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Auksion yaratish")],
            [KeyboardButton(text="Auksionni rejalashtirish")],
            [KeyboardButton(text="Auksionni boshlash")],
            [KeyboardButton(text="Auksionni to‘xtatish")],
            [KeyboardButton(text="⬅️ Orqaga")]
        ],
        resize_keyboard=True,
    )
    return keyboard


# --- BOT SETUP ---
logging.basicConfig(level=logging.INFO)
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

    
# ------- USER BALANCE UTILS -------
async def get_user_balance(user_id):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return user.balance if user else 0.0

async def add_user_balance(user_id, amount):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(id=user_id, balance=0.0)
            session.add(user)
        user.balance = (user.balance or 0) + amount
        await session.commit()

async def sub_user_balance(user_id, amount):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user and (user.balance or 0) >= amount:
            user.balance -= amount
            await session.commit()
            return True
        return False

async def set_trade_link(user_id, link):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(id=user_id, balance=0.0, trade_link=link)
            session.add(user)
        else:
            user.trade_link = link
        await session.commit()

async def get_trade_link(user_id):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return user.trade_link if user else ""

# --- HANDLERS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # User DBda yo‘q bo‘lsa yaratamiz
    async with AsyncSessionLocal() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(User(id=message.from_user.id, balance=0.0, trade_link=""))
            await session.commit()
    await message.answer(
        "Assalomu alaykum! LeGee Skins botiga xush kelibsiz.\n"
        "Bu yerda CS2 skinlarni sotib olishingiz, sotishingiz mumkin.",
        reply_markup=get_main_menu(message.from_user.id)
    )
async def cmd_start(message: types.Message, state: FSMContext):
    await get_or_create_user(message.from_user.id)
    await state.clear()
    await message.answer(
        "Assalomu alaykum! LeGee Skins botiga xush kelibsiz.",
        reply_markup=get_main_menu(message.from_user.id)
    )
    

@dp.message(F.text == "⬅️ Orqaga")
async def back_to_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Asosiy menyu", reply_markup=get_main_menu(message.from_user.id))

# --- Profil ---
@dp.message(F.text == "Profil")
async def profile_menu(message: types.Message):
    await get_or_create_user(message.from_user.id)
    await message.answer("Profil menyusi:", reply_markup=get_profile_menu())

@dp.message(F.text == "Trade silkam")
async def profile_trade_link(message: types.Message):
    link = await get_trade_link(message.from_user.id)
    if not link or link.strip() == "":
        await message.answer("⚠️ Trade silka ulanmagan!")
    else:
        await message.answer(f"Sizning trade silkangiz: {link}")

@dp.message(F.text == "Balansim")
async def profile_balance(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    await message.answer(f"Sizning hisobingizda: {user.balance:,.0f} so'm")

# --- DEPOSIT HANDLERS ---
@dp.message(F.text == "Depozit")
async def deposit_entry(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Qancha summa to‘ldirmoqchisiz? (so‘mda faqat raqam)")
    await state.set_state(DepositFSM.wait_amount)

@dp.message(DepositFSM.wait_amount)
async def deposit_get_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text.replace(" ", ""))
        if amount < 1000:
            await message.answer("Minimal depozit 1000 so‘m.")
            return
        await state.update_data(amount=amount)
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="1-usul: P2P karta (HUMO)")],
                [KeyboardButton(text="⬅️ Orqaga")]
            ],
            resize_keyboard=True
        )
        await state.set_state(DepositFSM.wait_method)
        await message.answer("To‘lov usulini tanlang:", reply_markup=kb)
    except:
        await message.answer("Faqat raqam kiriting (masalan: 200000)")

@dp.message(DepositFSM.wait_method)
async def deposit_select_method(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data["amount"]

    if message.text.startswith("1-usul"):
        msg = (
            "💳 <b>P2P HUMO karta orqali to‘lov</b>\n\n"
            "<b>Karta raqami:</b> <code>9860 1266 0216 2482</code>\n"
            "<b>Egasi:</b> Rajabboyev F.B.\n"
            f"<b>Summa:</b> {amount:,.0f} so‘m\n\n"
            "To‘lovni amalga oshiring va <b>chek yoki skrinshot</b> yuboring."
        )
        await state.update_data(method="p2p")
        await state.set_state(DepositFSM.wait_screenshot)  # ⬅️ yangi holat
        await message.answer(msg, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")

    elif message.text == "⬅️ Orqaga":
        await state.clear()
        await message.answer("Asosiy menyu", reply_markup=get_main_menu(message.from_user.id))

    else:
        await message.answer("To‘lov usulini tugmadan tanlang!")

@dp.message(DepositFSM.wait_card_number)
async def deposit_card_number(message: types.Message, state: FSMContext):
    await state.update_data(card_number=message.text.strip())
    await state.set_state(DepositFSM.wait_screenshot)
    await message.answer("Endi <b>to‘lov cheki yoki skrinshotini</b> rasm ko‘rinishida yuboring.", parse_mode="HTML")

@dp.message(DepositFSM.wait_screenshot, F.photo)
async def deposit_screenshot(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    method = data.get("method")
    card_number = data.get("card_number", "Kiritilmagan")
    admin_id = SUPER_ADMIN_ID if 'SUPER_ADMIN_ID' in globals() else ADMIN_IDS[0]
    msg = (
        f"🟢 <b>Yangi depozit so‘rovi</b>\n"
        f"User: <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a> (ID: <code>{message.from_user.id}</code>)\n"
        f"Summa: <b>{amount:,.0f}</b> so‘m\n"
        f"Usul: <b>{'P2P Karta' if method=='p2p' else 'CLICK Terminal'}</b>\n"
        f"Kartasi: <code>{card_number}</code>"
    )
    await bot.send_photo(
        admin_id, photo=message.photo[-1].file_id,
        caption=msg, parse_mode="HTML"
    )
    await message.answer(
        "Depozit so‘rovingiz adminlarga yuborildi. 1 soat ichida tekshiriladi. So‘rov tasdiqlansa balansingiz to‘ldiriladi.",
        reply_markup=get_main_menu(message.from_user.id)
    )
    await state.clear()

# --- Skin olish ---
@dp.message(F.text == "Skin olish")
async def buy_skin_category(message: types.Message, state: FSMContext):
    await state.set_state(BuySkin.category)
    await message.answer("Kategoriya tanlang:", reply_markup=get_category_kb())

@dp.message(BuySkin.category)
async def choose_item(message: types.Message, state: FSMContext):
    cat = message.text
    if cat not in SKIN_CATEGORIES:
        await message.answer("To'g'ri kategoriya tanlang!")
        return
    await state.update_data(category=cat)
    await state.set_state(BuySkin.item)
    await message.answer(f"{cat} uchun item tanlang:", reply_markup=get_items_kb(cat))

@dp.message(BuySkin.item)
async def show_skins(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat = data.get("category")
    item = message.text
    if item not in SKIN_CATEGORIES.get(cat, []):
        await message.answer("To'g'ri item tanlang!")
        return
    await state.update_data(item=item)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Skin).where(Skin.item == item))
        skins = result.scalars().all()
    if not skins:
        await message.answer("Bu item uchun skinlar yo'q.")
        return
    await state.set_state(BuySkin.select_skin)
    caption = ""
    for idx, skin in enumerate(skins, 1):
        caption += f"<b>{idx}) {skin.name}</b>\nHolati: {skin.condition}\nNarxi: {int(float(skin.price)):,.0f}\n\n"
    media = [InputMediaPhoto(media=skin.img) for skin in skins]
    await message.answer_media_group(media)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{i+1}-sotib olish", callback_data=f"buy_{i}")] for i in range(len(skins))
        ]
    )
    await message.answer(caption, reply_markup=kb)
    await state.update_data(skins=[{"id": s.id, "name": s.name, "condition": s.condition, "price": s.price, "img": s.img} for s in skins])

@dp.callback_query(F.data.startswith("buy_"), BuySkin.select_skin)
async def buy_skin_callback(call: types.CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_")[1])
    data = await state.get_data()
    skins = data.get("skins", [])
    skin = skins[idx]
    user_id = call.from_user.id
    balance = await get_user_balance(user_id)
    if balance < skin['price']:
        await call.message.answer(
            f"<b>Mablag‘ingiz yetarli emas!</b>\n"
            f"Skin narxi: {skin['price']:,.0f} so‘m\n"
            f"Balans: {balance:,.0f} so‘m\n"
            "Iltimos, <b>Profil → Depozit</b> orqali hisobingizni to‘ldiring.",
            reply_markup=get_main_menu(user_id)
        )
        await state.clear()
        await call.answer()
        return
    ok = await sub_user_balance(user_id, skin['price'])
    if not ok:
        await call.message.answer("Xatolik! Balansdan yechib bo‘lmadi.")
        await state.clear()
        await call.answer()
        return
    async with AsyncSessionLocal() as session:
        inv = Inventory(user_id=user_id, skin_id=skin['id'])
        session.add(inv)
        await session.commit()
    await call.message.answer(f"<b>{skin['name']}</b> skin sotib olindi va inventaringizga qo‘shildi!", reply_markup=get_main_menu(user_id))
    await state.clear()
    await call.answer()

# --- Skin sotish ---
@dp.message(F.text == "Skin sotish")
async def sell_skin(message: types.Message, state: FSMContext):
    await state.set_state(SellSkin.name)
    await message.answer("Sotmoqchi bo'lgan skin nomini kiriting:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⬅️ Orqaga")]], resize_keyboard=True))

@dp.message(SellSkin.name)
async def sell_skin_name(message: types.Message, state: FSMContext):
    try:
        print("SellSkin.name handler ishladi!")  # DEBUG
        await state.update_data(name=message.text)
        await state.set_state(SellSkin.condition)
        await message.answer("Skin holatini kiriting (masalan: Yangi, Ishlatilgan):", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        print(f"Xatolik SellSkin.name handlerda: {e}")
        await message.answer("Xatolik yuz berdi. Admin bilan bog‘laning.")

@dp.message(SellSkin.condition)
async def sell_skin_condition(message: types.Message, state: FSMContext):
    await state.update_data(condition=message.text)
    await state.set_state(SellSkin.photo)
    await message.answer("Skin rasmini yuboring:")

@dp.message(SellSkin.photo, F.photo)
async def sell_skin_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(SellSkin.price)
    await message.answer("Skin narxini kiriting (masalan: 100000):")

@dp.message(SellSkin.price)
async def sell_skin_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(" ", ""))
        await state.update_data(price=price)
    except Exception:
        await message.answer("Faqat son kiriting! Narx (masalan: 100000):")
        return
    data = await state.get_data()
    await state.set_state(SellSkin.confirm)
    text = (
        f"Skin nomi: {data['name']}\n"
        f"Holati: {data['condition']}\n"
        f"Narxi: {data['price']:,.0f}\n"
        f"Hammasi to‘g‘rimi?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Tasdiqlash", callback_data="sell_confirm"),
             InlineKeyboardButton(text="Bekor qilish", callback_data="sell_cancel")]
        ]
    )
    await message.answer_photo(data['photo'], caption=text, reply_markup=kb)

@dp.callback_query(F.data == "sell_confirm", SellSkin.confirm)
async def sell_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with AsyncSessionLocal() as session:
        req = SellRequest(
            user_id=call.from_user.id,
            name=data["name"],
            condition=data["condition"],
            price=data["price"],
            img=data["photo"],
            status="pending"
        )
        session.add(req)
        await session.commit()
    await call.message.answer("So‘rovingiz yuborildi. Adminlar ko‘rib chiqadi.", reply_markup=get_main_menu(call.from_user.id))
    await state.clear()
    await call.message.delete()

@dp.callback_query(F.data == "sell_cancel", SellSkin.confirm)
async def sell_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("So‘rov bekor qilindi.", reply_markup=get_main_menu(call.from_user.id))
    await state.clear()
    await call.message.delete()

# --- Inventar ---
@dp.message(F.text == "Inventar")
async def inventory_menu(message: types.Message):
    await message.answer("Inventar bo‘limi:", reply_markup=get_inventory_kb())

@dp.message(F.text == "Trade silka biriktirish")
async def trade_link(message: types.Message, state: FSMContext):
    await state.set_state(InventoryFSM.wait_trade_url)
    await message.answer("Steam trade silkangizni kiriting:")

@dp.message(InventoryFSM.wait_trade_url)
async def save_trade_url(message: types.Message, state: FSMContext):
    await set_trade_link(message.from_user.id, message.text)
    await message.answer("Trade silka biriktirildi!", reply_markup=get_inventory_kb())
    await state.clear()

@dp.message(F.text == "Skinlarim")
async def my_skins(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Inventory).where(Inventory.user_id == user.id))
        invs = result.scalars().all()
        if not invs:
            await message.answer("Sizda hali skin yo‘q.")
            return
        for inv in invs:
            skin = await session.get(Skin, inv.skin_id)
            if skin:
                kb = get_skin_action_kb()
                await message.answer_photo(
                    skin.img,
                    caption=f"<b>{skin.name}</b>\nHolati: {skin.condition}\nNarxi: {skin.price:,.0f}",
                    reply_markup=kb
                )

@dp.callback_query(F.data == "withdraw_skin")
async def withdraw_skin(call: types.CallbackQuery):
    await call.message.answer("So‘rovingiz adminlarga yuborildi. 2 soat ichida Steamga chiqariladi.")

@dp.callback_query(F.data == "sell_my_skin")
async def sell_from_inventory(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Skinni sotish uchun adminlarga so‘rov yuborildi.")
    
# --- ADMIN TASDIQLASH ---
@dp.message(F.text.startswith("!tasdiqla "))
async def admin_confirm_deposit(message: types.Message):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != SUPER_ADMIN_ID:
        return
    try:
        data = message.text.split()
        user_id = int(data[1])
        amount = int(data[2])
        await add_user_balance(user_id, amount)
        await message.answer(f"✅ Userga {amount:,.0f} so‘m balans qo‘shildi.")
        await bot.send_message(user_id, f"✅ Depozit so‘rovingiz admin tomonidan tasdiqlandi! Balansingiz yangilandi.")
    except Exception as e:
        await message.answer("Xatolik! Foydalanuvchi ID va summani to‘g‘ri kiriting.\nMasalan: <code>!tasdiqla 123456789 100000</code>", parse_mode="HTML")

# --- Auksion ---
@dp.message(F.text == "Auksion")
async def auction_menu(message: types.Message):
    await get_or_create_user(message.from_user.id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Auction).where(Auction.status == "active"))
        auction = result.scalars().first()
    if not auction:
        await message.answer("Hozircha auksion mavjud emas.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Narxni oshirish", callback_data="auction_bid")]
        ]
    )
    await message.answer_photo(
        auction.skin_img,
        caption=(
            f"<b>Auksion!</b>\n"
            f"Boshlang‘ich narx: {auction.start_price:,.0f}\n"
            f"O‘sish: +{auction.step:,.0f}\n"
            f"Hozirgi narx: {auction.current_price:,.0f}\n"
            f"Yutayotgan: {auction.current_winner or 'Hali yo‘q'}\n"
            f"Tugash vaqti: {auction.end_time}"
        ),
        reply_markup=kb
    )

@dp.callback_query(F.data == "auction_bid")
async def auction_bid(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Auction).where(Auction.status == "active"))
        auction = result.scalars().first()
        if not auction:
            await call.message.answer("Auksion yo‘q.")
            return
        new_price = auction.current_price + auction.step
        bal = await get_user_balance(user_id)
        if bal < new_price:
            await call.message.answer("Balansingizda yetarli mablag‘ yo‘q. Profil → Depozit orqali to‘ldiring.")
            return
        auction.current_price = new_price
        auction.current_winner = user_id
        await session.commit()
    await call.message.answer(f"Narz oshirildi! {new_price:,.0f} so‘m. Siz yetakchisiz.")

# --- Admin panel ----
@dp.message(F.text == "Admin panel")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != SUPER_ADMIN_ID:
        await message.answer("Siz admin emassiz.")
        return
    await message.answer("Admin paneli:", reply_markup=get_admin_panel_kb(message.from_user.id))

@dp.message(F.text == "Skin qo'shish")
async def admin_skin_add_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Siz admin emassiz.")
        return
    await state.set_state(AddSkin.category)
    await message.answer("Kategoriya tanlang:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cat)] for cat in SKIN_CATEGORIES] + [[KeyboardButton(text="⬅️ Orqaga")]],
        resize_keyboard=True))

@dp.message(AddSkin.category)
async def admin_skin_add_category(message: types.Message, state: FSMContext):
    cat = message.text.strip()
    if cat not in SKIN_CATEGORIES:
        await message.answer("Kategoriya nomini tugmadan tanlang!")
        return
    await state.update_data(category=cat)
    await state.set_state(AddSkin.item)
    await message.answer("Item tanlang:", reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=item)] for item in SKIN_CATEGORIES[cat]] + [[KeyboardButton(text="⬅️ Orqaga")]],
        resize_keyboard=True))

@dp.message(AddSkin.item)
async def admin_skin_add_item(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cat = data['category']
    item = message.text.strip()
    if item not in SKIN_CATEGORIES[cat]:
        await message.answer("Item nomini tugmadan tanlang!")
        return
    await state.update_data(item=item)
    await state.set_state(AddSkin.name)
    await message.answer("Skin nomini kiriting:", reply_markup=ReplyKeyboardRemove())

@dp.message(AddSkin.name)
async def admin_skin_add_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddSkin.condition)
    await message.answer("Skin holatini kiriting (masalan: Yangi, Ishlatilgan):")

@dp.message(AddSkin.condition)
async def admin_skin_add_condition(message: types.Message, state: FSMContext):
    await state.update_data(condition=message.text.strip())
    await state.set_state(AddSkin.price)
    await message.answer("Skin narxini kiriting (masalan: 100000):")

@dp.message(AddSkin.price)
async def admin_skin_add_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.replace(" ", ""))
        await state.update_data(price=price)
    except Exception:
        await message.answer("Faqat son kiriting! Narx (masalan: 100000):")
        return
    await state.set_state(AddSkin.img)
    await message.answer("Skin rasmiga to‘g‘ridan-to‘g‘ri havola (https://...) kiriting:")

@dp.message(AddSkin.img)
async def admin_skin_add_img(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("http"):
        await message.answer("To‘g‘ri rasm havolasi kiriting!")
        return
    await state.update_data(img=url)
    data = await state.get_data()
    msg = (
        f"<b>Kategoriya:</b> {data['category']}\n"
        f"<b>Item:</b> {data['item']}\n"
        f"<b>Nomi:</b> {data['name']}\n"
        f"<b>Holati:</b> {data['condition']}\n"
        f"<b>Narxi:</b> {data['price']:,.0f}\n"
        f"<b>Rasm:</b> {data['img']}\n"
        f"Bular to‘g‘rimi? Tasdiqlang."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ha", callback_data="addskin_confirm"),
             InlineKeyboardButton(text="Bekor", callback_data="addskin_cancel")]
        ]
    )
    await message.answer_photo(data['img'], caption=msg, reply_markup=kb, parse_mode="HTML")
    await state.set_state(AddSkin.confirm)

@dp.callback_query(F.data == "addskin_confirm", AddSkin.confirm)
async def admin_skin_add_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with AsyncSessionLocal() as session:
        skin = Skin(
            category=data['category'],
            item=data['item'],
            name=data['name'],
            condition=data['condition'],
            price=data['price'],
            img=data['img']
        )
        session.add(skin)
        await session.commit()
    await call.message.answer("Skin bazaga qo‘shildi!", reply_markup=get_main_menu(call.from_user.id))
    await state.clear()
    await call.message.delete()

@dp.callback_query(F.data == "addskin_cancel", AddSkin.confirm)
async def admin_skin_add_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Skin joylash bekor qilindi.", reply_markup=get_main_menu(call.from_user.id))
    await state.clear()
    await call.message.delete()


@dp.message(F.text == "Skin o'chirish")
async def admin_skin_delete_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != SUPER_ADMIN_ID:
        await message.answer("Siz admin emassiz.")
        return
    await state.set_state(DeleteSkinFSM.waiting_item_name)
    await message.answer("Qaysi item (masalan, AK-47, Karambit) uchun skin o‘chirmoqchisiz? Nomini kiriting:", reply_markup=ReplyKeyboardRemove())

@dp.message(DeleteSkinFSM.waiting_item_name)
async def admin_skin_delete_choose_item(message: types.Message, state: FSMContext):
    item = message.text.strip()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Skin).where(Skin.item == item))
        skins = result.scalars().all()
    if not skins:
        await message.answer("Bu item uchun skinlar topilmadi.")
        await state.clear()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{skin.name} | {int(skin.price):,} so'm", callback_data=f"del_skin_{skin.id}")]
            for skin in skins
        ]
    )
    await state.set_state(DeleteSkinFSM.waiting_skin_select)
    await message.answer("O‘chirmoqchi bo‘lgan skinni tanlang:", reply_markup=kb)

@dp.callback_query(F.data.startswith("del_skin_"), DeleteSkinFSM.waiting_skin_select)
async def admin_skin_delete_confirm(call: types.CallbackQuery, state: FSMContext):
    skin_id = int(call.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        skin = await session.get(Skin, skin_id)
    if not skin:
        await call.message.answer("Skin topilmadi.")
        await state.clear()
        return
    msg = (
        f"<b>Skin o‘chirish</b>\n"
        f"Nomi: {skin.name}\n"
        f"Item: {skin.item}\n"
        f"Narxi: {int(skin.price):,} so‘m\n"
        f"Haqiqatan o‘chirmoqchimisiz?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Ha, o‘chirish", callback_data=f"del_skin_yes_{skin.id}")],
            [InlineKeyboardButton(text="❌ Bekor", callback_data="del_skin_cancel")]
        ]
    )
    await state.set_state(DeleteSkinFSM.confirm)
    await call.message.answer_photo(skin.img, caption=msg, reply_markup=kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("del_skin_yes_"), DeleteSkinFSM.confirm)
async def admin_skin_delete_do(call: types.CallbackQuery, state: FSMContext):
    skin_id = int(call.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        skin = await session.get(Skin, skin_id)
        if skin:
            await session.delete(skin)
            await session.commit()
            await call.message.answer("Skin o‘chirildi!", reply_markup=get_admin_panel_kb(call.from_user.id))
        else:
            await call.message.answer("Skin topilmadi yoki allaqachon o‘chirilgan.")
    await state.clear()
    await call.message.delete()

@dp.callback_query(F.data == "del_skin_cancel", DeleteSkinFSM.confirm)
async def admin_skin_delete_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("O‘chirish bekor qilindi.", reply_markup=get_admin_panel_kb(call.from_user.id))
    await state.clear()
    await call.message.delete()

def get_sell_request_kb(request_id):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"sell_accept_{request_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"sell_reject_{request_id}")
            ]
        ]
    )

@dp.message(F.text == "Sotish zayafkalari")
async def admin_sell_requests(message: types.Message):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != SUPER_ADMIN_ID:
        await message.answer("Siz admin emassiz.")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SellRequest).where(SellRequest.status == "pending")
        )
        requests = result.scalars().all()

    if not requests:
        await message.answer("Hozircha skin sotish zayavkasi yo'q.")
        return

    for req in requests:
        user_link = f"<a href='tg://user?id={req.user_id}'>User</a>"
        await message.answer_photo(
            req.img,
            caption=(
                f"Skin sotish zayavkasi:\n"
                f"User: {user_link}\n"
                f"Skin: {req.name}\n"
                f"Holat: {req.condition}\n"
                f"Narx: {req.price}\n"
                f"Status: {req.status}"
            ),
            parse_mode="HTML",
            reply_markup=get_sell_request_kb(req.id)
        )

@dp.callback_query(lambda c: c.data.startswith("sell_accept_") or c.data.startswith("sell_reject_"))
async def handle_sell_request_action(callback: types.CallbackQuery):
    action, req_id = callback.data.split("_")[1], int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        req = await session.get(SellRequest, req_id)
        if not req:
            await callback.answer("Zayavka topilmadi.", show_alert=True)
            return

        user_link = f"<a href='tg://user?id={req.user_id}'>User</a>"

        if action == "accept":
            req.status = "accepted"
            await session.commit()
            await callback.message.answer(
                f"{user_link} yuborgan skin sotish zayavkasi QABUL QILINDI!\nAdmin unga aloqaga chiqishi mumkin.",
                parse_mode="HTML"
            )
            try:
                await bot.send_message(
                    req.user_id,
                    "Skin sotish zayavkangiz admin tomonidan QABUL QILINDI. Admin siz bilan aloqaga chiqadi."
                )
            except Exception:
                pass
        elif action == "reject":
            req.status = "rejected"
            await session.commit()
            await callback.message.answer(
                f"{user_link} yuborgan skin sotish zayavkasi RAD ETILDI.",
                parse_mode="HTML"
            )
            try:
                await bot.send_message(
                    req.user_id,
                    "Skin sotish zayavkangiz admin tomonidan RAD ETILDI. Bu safar qabul qilinmadi."
                )
            except Exception:
                pass

        await callback.answer("Javob yuborildi.")

# --- AUKSION BLOK ---
@dp.message(F.text == "Auksion boshqarish")
async def admin_manage_auction(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != SUPER_ADMIN_ID:
        await message.answer("Siz admin emassiz.")
        return
    await message.answer("Auksion boshqaruv paneli:", reply_markup=get_auction_menu())
    
@dp.message(F.text == "Auksion yaratish")
async def create_auction_handler(message: types.Message, state: FSMContext):
    auction_state.update({
        "active": False, "https_img": None, "end_time": None,
        "name": None, "start_price": None, "step": None, "current_price": None,
        "leader_id": None, "leader_name": None, "bids": [],
        "rejalashtirildi": False, "started": False
    })
    await message.answer("Auksion uchun rasm havolasini (https://...) yuboring.")
    await state.set_state(AuctionFSM.wait_img)

@dp.message(AuctionFSM.wait_img)
async def auction_img_received(message: types.Message, state: FSMContext):
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("Faqat https:// yoki http:// bilan boshlanuvchi rasm havolasi yuboring!")
        return
    await state.update_data(https_img=url)
    await state.set_state(AuctionFSM.wait_name)
    await message.answer("Skin nomini kiriting (masalan: AWP | Dragon Lore):")

@dp.message(AuctionFSM.wait_name)
async def auction_name_received(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AuctionFSM.wait_time)
    await message.answer("Auksion tugash vaqtini kiriting (masalan: 2025-06-29 20:00):")

@dp.message(AuctionFSM.wait_time)
async def auction_time_received(message: types.Message, state: FSMContext):
    await state.update_data(end_time=message.text.strip())
    await state.set_state(AuctionFSM.wait_start_price)
    await message.answer("Boshlang‘ich narxni kiriting:")

@dp.message(AuctionFSM.wait_start_price)
async def auction_start_price_received(message: types.Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        await state.update_data(start_price=price)
        await state.set_state(AuctionFSM.wait_step)
        await message.answer("Auksion narx oshish bosqichini kiriting (masalan: 10000):")
    except Exception:
        await message.answer("Narxni faqat son shaklida kiriting!")

@dp.message(AuctionFSM.wait_step)
async def auction_step_received(message: types.Message, state: FSMContext):
    try:
        step = float(message.text.strip())
        data = await state.get_data()
        await state.update_data(step=step)
        await state.set_state(AuctionFSM.confirm)
        await message.answer_photo(
            data['https_img'],
            caption=(
                f"Auksion:\nNomi: {data['name']}\n"
                f"Tugash vaqti: {data['end_time']}\n"
                f"Boshlang‘ich narx: {data['start_price']:,.0f}\n"
                f"O‘sish bosqichi: {step:,.0f}\n"
                f"Auksionni rejalashtirish uchun 'Auksionni rejalashtirish' tugmasini bosing."
            ),
            reply_markup=get_auction_menu()
        )
    except Exception:
        await message.answer("Stepni faqat son shaklida kiriting!")

@dp.message(F.text == "Auksionni rejalashtirish")
async def auction_plan_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data or not data.get("https_img"):
        await message.answer("Avval auksion uchun ma'lumotlarni to'liq kiriting!")
        return
    auction_state.update({
        "https_img": data['https_img'],
        "end_time": data['end_time'],
        "name": data['name'],
        "start_price": float(data['start_price']),
        "step": float(data['step']),
        "current_price": float(data['start_price']),
        "rejalashtirildi": True,
        "active": False,
        "started": False,
        "leader_id": None,
        "leader_name": None,
        "bids": []
    })
    await message.answer("Auksion rejalashtirildi! Boshlash uchun 'Auksionni boshlash' tugmasini bosing.", reply_markup=get_auction_menu())

@dp.message(F.text == "Auksionni boshlash")
async def start_auction_handler(message: types.Message, state: FSMContext):
    if not (auction_state["rejalashtirildi"] and not auction_state["active"]):
        await message.answer("Auksion hali rejalashtirilmagan yoki allaqachon boshlangan.")
        return
    auction_state["active"] = True
    auction_state["started"] = True
    auction_state["current_price"] = auction_state["start_price"]
    auction_state["leader_id"] = None
    auction_state["leader_name"] = None
    auction_state["bids"] = []
    bid_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Narxni oshirish (+{auction_state['step']})", callback_data="bid_raise")]
        ]
    )
    caption = (
        f"🟢 Yangi auksion boshlandi!\n\n"
        f"Nomi: {auction_state['name']}\n"
        f"Tugash vaqti: {auction_state['end_time']}\n"
        f"Boshlang‘ich narx: {auction_state['start_price']}\n"
        f"O‘sish bosqichi: {auction_state['step']}\n"
        f"Joriy narx: {auction_state['current_price']}\n"
        f"Ishtirok etish uchun tugmani bosing!"
    )
    all_user_ids = get_all_user_ids()
    for user_id in all_user_ids:
        try:
            await message.bot.send_photo(chat_id=user_id, photo=auction_state["https_img"], caption=caption, reply_markup=bid_kb)
        except Exception as e:
            print(f"Xatolik: {user_id} ga yuborilmadi: {e}")
    await message.answer("Auksion boshlandi!", reply_markup=get_auction_menu())
    asyncio.create_task(auction_finish_timer(message.bot, auction_state["end_time"]))

@dp.message(F.text == "Auksion")
async def auction_menu(message: types.Message):
    if not auction_state["started"]:
        await message.answer("Hozircha auksion mavjud emas.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Narxni oshirish", callback_data="bid_raise")]
        ]
    )
    leader = auction_state["leader_name"] or "Hali yo‘q"
    await message.answer_photo(
        auction_state["https_img"],
        caption=(
            f"<b>Auksion!</b>\n"
            f"Nomi: {auction_state['name']}\n"
            f"Boshlang‘ich narx: {auction_state['start_price']:,.0f}\n"
            f"O‘sish: +{auction_state['step']:,.0f}\n"
            f"Hozirgi narx: {auction_state['current_price']:,.0f}\n"
            f"Yutayotgan: {leader}\n"
            f"Tugash vaqti: {auction_state['end_time']}"
        ),
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.message(F.text == "Auksionni to‘xtatish")
async def stop_auction_handler(message: types.Message):
    if not auction_state["active"]:
        await message.answer("Auksion faol emas!")
        return
    auction_state["active"] = False
    auction_state["started"] = False
    await message.answer("Auksion to‘xtatildi!", reply_markup=get_main_menu(message.from_user.id))
    await send_auction_result(message.bot, ADMIN_IDS[0], forced=True)

@dp.callback_query(F.data == "bid_raise")
async def bid_raise_handler(call: types.CallbackQuery):
    if not auction_state["active"]:
        await call.answer("Auksion tugagan yoki boshlanmagan!", show_alert=True)
        return
    user_id = call.from_user.id
    user_name = call.from_user.full_name
    if auction_state["leader_id"] == user_id:
        await call.answer("Siz allaqachon eng yuqori narxni taklif qildingiz!", show_alert=True)
        return

    auction_state["current_price"] += auction_state["step"]
    auction_state["leader_id"] = user_id
    auction_state["leader_name"] = user_name
    auction_state["bids"].append({"user_id": user_id, "user_name": user_name, "price": auction_state["current_price"]})

    bid_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Narxni oshirish (+{auction_state['step']})", callback_data="bid_raise")]
        ]
    )
    caption = (
        f"🟢 Auksion davom etmoqda!\n"
        f"Nomi: {auction_state['name']}\n"
        f"Joriy narx: {auction_state['current_price']}\n"
        f"Lider: {user_name}\n"
        f"Ishtirok etish uchun tugmani bosing!"
    )
    all_user_ids = get_all_user_ids()
    for user_id_broadcast in all_user_ids:
        try:
            await call.bot.send_photo(chat_id=user_id_broadcast, photo=auction_state["https_img"], caption=caption, reply_markup=bid_kb)
        except Exception as e:
            print(f"Xatolik: {user_id_broadcast} ga yuborilmadi: {e}")
    await call.answer("Narx oshirildi!", show_alert=False)

async def auction_finish_timer(bot, end_time_str):
    from datetime import datetime
    try:
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M")
        now = datetime.utcnow()
        delay = (end_time - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
    except Exception as e:
        print(f"End time format xatosi: {e}")
        return
    if auction_state["active"]:
        auction_state["active"] = False
        auction_state["started"] = False
        for admin_id in ADMIN_IDS:
            await send_auction_result(bot, admin_id)

async def save_skin(category, item, name, condition, img_https, price):
    async with AsyncSessionLocal() as session:
        skin = Skin(
            category=category,
            item=item,
            name=name,
            condition=condition,
            img=img_https,
            price=price
        )
        session.add(skin)
        await session.commit()
        await session.refresh(skin)
        return skin.id
    
async def add_to_inventory(user_id, skin_id):
    async with AsyncSessionLocal() as session:
        inv = Inventory(user_id=user_id, skin_id=skin_id)
        session.add(inv)
        await session.commit()

async def send_auction_result(bot, admin_id, forced=False):
    all_user_ids = get_all_user_ids()
    if auction_state["leader_id"]:
        winner_id = auction_state["leader_id"]
        winner_name = auction_state["leader_name"]
        winner_link = f'<a href="tg://user?id={winner_id}">{winner_name}</a>'
        natija_narx = auction_state['current_price']

        # 1. Skinni DB ga saqlash
        skin_id = await save_skin(
            category="Auksion",
            item="Auksion",
            name=auction_state["name"],
            condition="Yangi",
            img_https=auction_state["https_img"],
            price=natija_narx
        )

        # 2. Yutgan foydalanuvchi balansini tekshirish va pulni yechish
        async with AsyncSessionLocal() as session:
            from models import User
            user = await session.get(User, winner_id)
            if not user or (user.balance or 0) < natija_narx:
                await bot.send_message(winner_id, "Auksion uchun balansingiz yetarli emas, skin qo‘shilmadi!")
                await bot.send_message(admin_id, f"Yutgan foydalanuvchi ({winner_id}) balansida yetarli mablag‘ yo‘q.")
                return

            user.balance -= natija_narx
            await session.commit()

        # 3. Inventarga skin qo‘shish
        await add_to_inventory(winner_id, skin_id)

        # 4. Natija habarini yuborish
        result_text = (
            f"🏆 <b>Auksion yakuni!</b>\n"
            f"Nomi: {auction_state['name']}\n"
            f"Yutgan: {winner_link}\n"
            f"Natijaviy narx: {natija_narx}\n"
            f"Barcha bidlar: {auction_state['bids']}\n"
        )
        await bot.send_message(admin_id, result_text, parse_mode="HTML")
        await bot.send_message(winner_id, f"Tabriklaymiz! Siz auksionda g‘olib bo‘ldingiz va skin inventaringizga qo‘shildi.\n{result_text}", parse_mode="HTML")

        if auction_state["https_img"]:
            await bot.send_photo(admin_id, photo=auction_state["https_img"])
        if not forced:
            end_caption = f"Auksion tugadi! G‘olib: {winner_name}"
            for user_id in all_user_ids:
                try:
                    await bot.send_message(user_id, end_caption, reply_markup=get_main_menu(user_id))
                except Exception as e:
                    print(f"Userga tugaganini yuborilmadi: {e}")
    else:
        result_text = "Auksionda hech kim ishtirok etmadi yoki narx oshirilmadi."
        await bot.send_message(admin_id, result_text, reply_markup=get_main_menu(admin_id))
        if not forced:
            for user_id in all_user_ids:
                try:
                    await bot.send_message(user_id, "Auksion tugadi! G‘olib yo‘q.", reply_markup=get_main_menu(user_id))
                except Exception as e:
                    print(f"Userga tugaganini yuborilmadi: {e}")
    auction_state.update({
        "active": False, "https_img": None, "end_time": None, "name": None, "start_price": None,
        "step": None, "current_price": None, "leader_id": None, "leader_name": None, "bids": [],
        "rejalashtirildi": False, "started": False
    })

    
# --- Adminlarni boshqarish va statistika ---
@dp.message(F.text == "Adminlarni boshqarish")
async def admin_manage_admins(message: types.Message, state: FSMContext):
    if message.from_user.id != SUPER_ADMIN_ID:
        await message.answer("Faqat bosh admin adminlarni boshqara oladi.")
        return
    admins_list = "\n".join([str(a) for a in ADMIN_IDS])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Admin qo‘shish", callback_data="add_admin")],
            [InlineKeyboardButton(text="Admin olib tashlash", callback_data="remove_admin")],
            [InlineKeyboardButton(text="Statistika (txt)", callback_data="admin_stat")]
        ]
    )
    await message.answer(f"Hozirgi adminlar ID ro‘yxati:\n{admins_list}", reply_markup=kb)

@dp.callback_query(F.data == "add_admin")
async def add_admin_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Qo‘shmoqchi bo‘lgan admin Telegram ID raqamini kiriting:")
    await state.set_state(AdminManageFSM.add_admin_id)
    await call.answer()

@dp.message(F.state == AdminManageFSM.add_admin_id)
async def add_admin_id(message: types.Message, state: FSMContext):
    try:
        new_id = int(message.text.strip())
        if new_id in ADMIN_IDS:
            await message.answer("Bu ID allaqachon admin!")
        else:
            ADMIN_IDS.append(new_id)
            await message.answer(f"ID {new_id} adminlar ro‘yxatiga qo‘shildi.")
    except ValueError:
        await message.answer("Iltimos, faqat raqamli Telegram ID kiriting!")
    await state.clear()
    await message.answer("Admin paneli", reply_markup=get_admin_panel_kb())

@dp.callback_query(F.data == "remove_admin")
async def remove_admin_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Olib tashlamoqchi bo‘lgan admin Telegram ID raqamini kiriting:")
    await state.set_state(AdminManageFSM.remove_admin_id)
    await call.answer()

@dp.message(F.state == AdminManageFSM.remove_admin_id)
async def remove_admin_id(message: types.Message, state: FSMContext):
    try:
        remove_id = int(message.text.strip())
        if remove_id in ADMIN_IDS:
            ADMIN_IDS.remove(remove_id)
            await message.answer(f"ID {remove_id} adminlar ro‘yxatidan olib tashlandi.")
        else:
            await message.answer("Bu ID adminlar ro‘yxatida yo‘q!")
    except ValueError:
        await message.answer("Iltimos, faqat raqamli Telegram ID kiriting!")
    await state.clear()
    await message.answer("Admin paneli", reply_markup=get_admin_panel_kb())

@dp.callback_query(F.data == "admin_stat")
async def admin_stat(call: types.CallbackQuery):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AdminAction))
        actions = result.scalars().all()
    lines = []
    for a in actions:
        lines.append(f"{a.created_at} | {a.admin_id} | {a.action_type} | {a.target_user} | {a.detail}")
    filename = "admin_stat.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(filename, "rb") as f:
        await call.message.answer_document(types.FSInputFile(filename), caption="Adminlar statistikasi")
    os.remove(filename)
    await call.answer()

# --- Fallback ---
@dp.message()
async def fallback(message: types.Message):
    await message.answer("Menyudagi tugmalardan foydalaning.")
async def bot_main():
    await dp.start_polling(bot)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await init_db()
    logging.info("🤖 Bot ishga tushdi (polling)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot to‘xtatildi.")
