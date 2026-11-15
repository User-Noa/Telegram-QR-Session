#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=============================================================================
📱 Telegram QR Code Session Generator (Telethon)
=============================================================================
- Generates an ASCII QR Code directly in the terminal for quick login.
- Supports Two-Factor Authentication (2FA / Two-Step Verification).
- Automatically refreshes the QR code when it expires.
- Saves the authorized .session file in the sessions directory.
=============================================================================
"""

import os
import sys
import getpass
import asyncio
import qrcode
from telethon import TelegramClient, errors

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

from config import API_ID, API_HASH, SESSIONS_DIR, PROXY


def print_qr_in_terminal(url: str):
    """Generates and prints a high-contrast ASCII QR code in the terminal."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)

    print("\n" + "=" * 50)
    print("📲 لطفا این کیو‌آرکد را با تلگرام گوشی اسکن کنید:")
    print("   Settings > Devices > Link Desktop Device")
    print("=" * 50 + "\n")

    # Invert=True renders white on black (perfect for dark terminals)
    qr.print_ascii(invert=True)

    print("\n" + "-" * 50)
    print(f"🔗 یا از این لینک مستقیم استفاده کنید:\n{url}")
    print("-" * 50 + "\n")


async def create_session_with_qr(session_name: str):
    session_file = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    os.makedirs(SESSIONS_DIR, exist_ok=True)

    print(f"\n🚀 شروع فرآیند ساخت سشن: [{session_name}]")
    print(f"📁 مسیر ذخیره فایل سشن: {session_file}")

    # Initialize client (without auto-login prompt)
    client = TelegramClient(session_file, API_ID, API_HASH, proxy=PROXY)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"\n✅ این سشن از قبل لاگین است!")
        print(f"👤 نام: {me.first_name} | نام‌کاربری: @{me.username} | شناسه: {me.id}")
        await client.disconnect()
        return

    qr_login = await client.qr_login()

    logged_in_user = None

    while True:
        # Display QR code in terminal
        print_qr_in_terminal(qr_login.url)
        print("⏳ منتظر اسکن کیو‌آرکد توسط شما (مهلت: ۳۰ ثانیه)...")

        try:
            # Wait for user to scan the code (None syncs directly with Telegram server expiry ~30s)
            logged_in_user = await qr_login.wait()
            break

        except asyncio.TimeoutError:
            print("\n🔄 کیو‌آرکد منقضی شد! در حال دریافت کیو‌آرکد جدید...")
            await qr_login.recreate()
            continue

        except errors.SessionPasswordNeededError:
            print("\n🔐 این اکانت دارای تایید دو مرحله‌ای (2FA) است.")
            while True:
                try:
                    pwd = getpass.getpass("🔑 لطفا رمز تایید دو مرحله‌ای (2FA) خود را وارد کنید: ")
                    logged_in_user = await client.sign_in(password=pwd)
                    break
                except errors.PasswordHashInvalidError:
                    print("❌ رمز وارد شده اشتباه است! لطفا دوباره تلاش کنید.")
                except Exception as e:
                    print(f"❌ خطا در تایید رمز دو مرحله‌ای: {e}")
                    break
            break

        except Exception as e:
            print(f"\n❌ خطای غیرمنتظره در فرآیند لاگین: {e}")
            await client.disconnect()
            return

    if logged_in_user:
        me = await client.get_me()
        print("\n" + "🎉" * 25)
        print("✅ لاگین با موفقیت کامل انجام شد!")
        print(f"👤 نام: {me.first_name} {me.last_name or ''}")
        print(f"🆔 شناسه کاربری: {me.id}")
        print(f"📞 شماره تلفن: {me.phone or 'مخفی'}")
        print(f"🔗 یوزرنیم: @{me.username or 'ندارد'}")
        print(f"💾 سشن با موفقیت ذخیره شد در: {session_file}")
        print("🎉" * 25 + "\n")

    await client.disconnect()


def main():
    session_name = None
    if len(sys.argv) > 1:
        session_name = sys.argv[1].replace(".session", "").strip()
    
    if not session_name:
        try:
            session_name = input("نام سشن مورد نظر را وارد کنید (مثلا my_account): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nعملیات لغو شد.")
            return

    if not session_name:
        session_name = "new_qr_session"

    try:
        asyncio.run(create_session_with_qr(session_name))
    except KeyboardInterrupt:
        print("\n\n🛑 عملیات توسط کاربر متوقف شد.")


if __name__ == "__main__":
    main()
