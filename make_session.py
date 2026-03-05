import asyncio
import os

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    ApiIdPublishedFloodError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberFloodError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession


load_dotenv("/Users/rosegoldknight/Documents/Работа/Парсер/.env")
API_ID = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")


async def login_by_phone(client: TelegramClient) -> str:
    phone = input("Телефон (в формате +7...): ").strip()
    try:
        sent = await client.send_code_request(phone)
    except ApiIdInvalidError:
        raise RuntimeError("Неверные TG_API_ID/TG_API_HASH")
    except ApiIdPublishedFloodError:
        raise RuntimeError("Этот API ID ограничен Telegram (published flood). Создайте новый app на my.telegram.org")
    except PhoneNumberFloodError:
        raise RuntimeError("Слишком много попыток. Подождите и повторите позже")
    except Exception as e:
        raise RuntimeError(f"Не удалось отправить код: {e.__class__.__name__}: {e}")

    print(f"Код отправлен. Тип: {getattr(sent.type, '__class__', type(sent.type)).__name__}")
    code = input("Код из Telegram: ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except PhoneCodeInvalidError:
        raise RuntimeError("Неверный код")
    except PhoneCodeExpiredError:
        raise RuntimeError("Код истёк. Запросите новый")
    except SessionPasswordNeededError:
        password = input("Пароль 2FA: ").strip()
        await client.sign_in(password=password)
    return client.session.save()


async def login_by_qr(client: TelegramClient) -> str:
    qr = await client.qr_login()
    print("\nОткройте Telegram на телефоне -> Настройки -> Устройства -> Подключить устройство.")
    print("Ссылка для входа (QR login):")
    print(qr.url)
    print("Подтвердите вход в приложении Telegram...")
    await qr.wait()
    return client.session.save()


async def main() -> None:
    if not API_ID or not API_HASH:
        raise RuntimeError("В .env должны быть TG_API_ID и TG_API_HASH")

    method = input("Способ входа: 1=код, 2=QR (по умолчанию 1): ").strip() or "1"
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        if await client.is_user_authorized():
            session = client.session.save()
        elif method == "2":
            session = await login_by_qr(client)
        else:
            session = await login_by_phone(client)
    finally:
        await client.disconnect()
    print("\n=== TG_STRING_SESSION ===")
    print(session)
    print("=== END ===\n")


if __name__ == "__main__":
    asyncio.run(main())
