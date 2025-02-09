import logging
import requests
import asyncio
import sqlite3
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

# Configurar logging para depuración
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = "7584626634:AAGGrpBUdAVM1GdDa8kaWCzyndLtdcaP0uI"

# URLs de la API
LOGIN_URL = "https://services.prod.p2p.mftech.io/login"
BALANCE_URL = "https://services.prod.p2p.mftech.io/v2/account/balance"

HEADERS = {
    "accept": "application/json",
    "content-type": "application/json;charset=UTF-8",
    "x-app-version": "5.1.1",
    "x-device-id": "a15381d6eaa1ccb4",
    "accept-encoding": "gzip, deflate, br",
    "user-agent": "okhttp/4.11.0"
}

checking_active = False  # Estado del chequeo automático
interval = 3600  # Intervalo en segundos (1 hora por defecto)
check_interval = 60  # Intervalo de revisión de cuentas en segundos (25 segundos)
history = []  # Lista para almacenar el historial de correos revisados
auto_check_task = None  # Tarea asíncrona para el chequeo automático

def init_db():
    conn = sqlite3.connect("accounts.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def add_account(email, password):
    conn = sqlite3.connect("accounts.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO accounts (email, password) VALUES (?, ?)", (email, password))
    conn.commit()
    conn.close()

def add_multiple_accounts(accounts_list):
    conn = sqlite3.connect("accounts.db")
    cursor = conn.cursor()
    for email, password in accounts_list:
        cursor.execute("INSERT OR IGNORE INTO accounts (email, password) VALUES (?, ?)", (email, password))
    conn.commit()
    conn.close()

def get_accounts():
    conn = sqlite3.connect("accounts.db")
    cursor = conn.cursor()
    cursor.execute("SELECT email, password FROM accounts")
    accounts = cursor.fetchall()
    conn.close()
    return accounts

def iniciar_sesion(email, password):
    session = requests.Session()
    login_data = {"username": email, "password": password}
    try:
        response = session.post(LOGIN_URL, headers=HEADERS, json=login_data)
        response.raise_for_status()
        json_response = response.json()
        access_token = json_response.get("accessToken")
        cookies = session.cookies.get_dict()

        if access_token:
            return access_token, cookies
    except requests.RequestException:
        return None, None

def obtener_balance(access_token, cookies):
    if not access_token or not cookies:
        return "❌ No se pudo obtener el balance."
    headers_balance = HEADERS.copy()
    headers_balance["authorization"] = f"Bearer {access_token}"
    headers_balance["x-access-token"] = access_token
    headers_balance["cookie"] = "; ".join([f"{key}={value}" for key, value in cookies.items()])
    try:
        response = requests.get(BALANCE_URL, headers=headers_balance)
        response.raise_for_status()
        json_response = response.json()
        balance = json_response.get("balance", {}).get("available", "N/A")
        return f"💰 Balance disponible: {balance}"
    except requests.RequestException:
        return "❌ No se pudo obtener el balance."

async def auto_check(update: Update, context: CallbackContext):
    global checking_active, interval, check_interval

    while checking_active:
        # Realiza el chequeo (esto puede ser una función que verifique el saldo de las cuentas)
        accounts = get_accounts()  # Obtener las cuentas almacenadas
        for email, password in accounts:
            access_token, cookies = iniciar_sesion(email, password)
            if access_token:
                balance = obtener_balance(access_token, cookies)
                await update.message.reply_text(f"📧 {email}\n{balance}")
            else:
                await update.message.reply_text(f"📧 {email}\n❌ Credenciales incorrectas o error en la API.")
            
            # Espera de 25 segundos entre cada cuenta
            await asyncio.sleep(check_interval)
        
        # Espera el tiempo configurado antes de volver a hacer el chequeo
        await asyncio.sleep(interval)

async def add_multiple_accounts_command(update: Update, context: CallbackContext):
    await update.message.reply_text("✍️ Envíame las cuentas a agregar, una por línea, usando el formato 'email:password'.")
    await update.message.reply_text("Ejemplo:\nemail1@example.com:password1\nemail2@example.com:password2")

async def receive_multiple_accounts(update: Update, context: CallbackContext):
    # Se recibe el mensaje de cuentas
    message = update.message.text
    accounts = []
    
    # Se separan las cuentas por línea
    lines = message.split("\n")
    
    for line in lines:
        # Se valida el formato de la cuenta "email:password"
        if ":" in line:
            email, password = line.split(":", 1)
            accounts.append((email.strip(), password.strip()))
    
    if accounts:
        # Agregar las cuentas a la base de datos
        add_multiple_accounts(accounts)
        await update.message.reply_text(f"✅ {len(accounts)} cuentas han sido añadidas.")
    else:
        await update.message.reply_text("⚠️ No se encontró ninguna cuenta válida para agregar.")

async def toggle_check(update: Update, context: CallbackContext):
    global checking_active, auto_check_task

    if checking_active:
        checking_active = False
        if auto_check_task:
            auto_check_task.cancel()  # Detener la tarea si está en ejecución
            await update.message.reply_text("🛑 Chequeo automático detenido.")
        else:
            await update.message.reply_text("⚠️ No hay tarea de chequeo en ejecución.")
    else:
        checking_active = True
        auto_check_task = asyncio.create_task(auto_check(update, context))  # Iniciar el chequeo automático en segundo plano
        await update.message.reply_text("🔄 Chequeo automático activado.")

async def set_interval(update: Update, context: CallbackContext):
    global interval
    try:
        new_interval = int(context.args[0])
        interval = new_interval * 60  # Convertir a segundos
        await update.message.reply_text(f"⏳ Intervalo cambiado a {new_interval} minutos.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Usa: /setinterval [minutos]")

async def list_accounts(update: Update, context: CallbackContext):
    accounts = get_accounts()
    if accounts:
        account_list = "\n".join([f"{email}" for email, _ in accounts])
        await update.message.reply_text(f"📧 Cuentas almacenadas:\n{account_list}")
    else:
        await update.message.reply_text("❌ No hay cuentas almacenadas.")

async def clear_accounts(update: Update, context: CallbackContext):
    conn = sqlite3.connect("accounts.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Todas las cuentas han sido borradas.")

async def add_account_command(update: Update, context: CallbackContext):
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usa: /add_account [email] [password]")
        return
    email, password = context.args
    add_account(email, password)
    await update.message.reply_text(f"✅ Cuenta {email} añadida para el chequeo automático.")

async def manual_check(update: Update, context: CallbackContext):
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Usa: /manual_check [email] [password]")
        return
    email, password = context.args
    access_token, cookies = iniciar_sesion(email, password)
    if access_token:
        balance = obtener_balance(access_token, cookies)
        await update.message.reply_text(f"📧 {email}\n{balance}")
    else:
        await update.message.reply_text(f"📧 {email}\n❌ Credenciales incorrectas o error en la API.")

async def export_history(update: Update, context: CallbackContext):
    if history:
        history_text = "\n".join(history)
        await update.message.reply_text(f"📜 Historial de correos revisados:\n{history_text}")
    else:
        await update.message.reply_text("❌ No hay historial disponible.")

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "¡Bienvenido al bot! Aquí tienes los comandos disponibles:\n\n"
        "/start - Inicia el bot y muestra las opciones interactivas.\n"
        "/toggle_check - Activa o desactiva el chequeo automático de cuentas.\n"
        "/setinterval [minutos] - Cambia el intervalo de revisión automática.\n"
        "/add_account [email] [password] - Agrega una cuenta para el chequeo automático.\n"
        "/manual_check [email] [password] - Revisa manualmente el saldo de una cuenta.\n"
        "/list_accounts - Muestra las cuentas almacenadas en la base de datos.\n"
        "/clear_accounts - Borra todas las cuentas guardadas.\n"
        "/export_history - Muestra el historial de correos revisados.\n"
        "/add_multiple_accounts - Agrega cuentas masivas usando el formato email:password.\n\n"
        "Para más ayuda o información, puedes escribir cualquier pregunta que tengas. 😊"
    )


def main():
    print("🚀 Iniciando el bot...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("toggle_check", toggle_check))
    app.add_handler(CommandHandler("setinterval", set_interval))
    app.add_handler(CommandHandler("add_account", add_account_command))
    app.add_handler(CommandHandler("manual_check", manual_check))
    app.add_handler(CommandHandler("list_accounts", list_accounts))
    app.add_handler(CommandHandler("clear_accounts", clear_accounts))
    app.add_handler(CommandHandler("export_history", export_history))
    app.add_handler(CommandHandler("add_multiple_accounts", add_multiple_accounts_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_multiple_accounts))

    app.run_polling()


if __name__ == "__main__":
    main()
