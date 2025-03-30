import json
import asyncio
from pyppeteer import launch
from datetime import datetime, timedelta
import aiofiles
import random
import requests
import os
import re

# 从环境变量中获取 Telegram Bot Token 和 Chat ID
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def format_to_iso(date):
    """格式化时间为 ISO 标准"""
    return date.strftime('%Y-%m-%d %H:%M:%S')

async def delay_time(ms):
    """延迟指定毫秒"""
    await asyncio.sleep(ms / 1000)

# 全局浏览器实例
browser = None

# Telegram 消息内容
message = ""

def get_service_name(panel):
    """
    自动匹配 panel0 - panel16，转换为 S0 - S16
    """
    match = re.search(r'panel(\d+)\.serv00\.com', panel)
    if match:
        return f"S{match.group(1)}"
    return panel  # 如果 panel 不符合格式，则直接返回原 panel 作为名称

async def login(username, password, panel):
    """登录面板"""
    global browser

    page = None  # 确保 page 在任何情况下都被定义
    serviceName = get_service_name(panel)  # 获取服务名称
    
    try:
        if not browser:
            browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])

        page = await browser.newPage()
        url = f'https://{panel}/login/?next=/'
        await page.goto(url)

        username_input = await page.querySelector('#id_username')
        if username_input:
            await page.evaluate('''(input) => input.value = ""''', username_input)

        await page.type('#id_username', username)
        await page.type('#id_password', password)

        login_button = await page.querySelector('#submit')
        if login_button:
            await login_button.click()
        else:
            raise Exception('无法找到登录按钮')

        await page.waitForNavigation()

        is_logged_in = await page.evaluate('''() => {
            const logoutButton = document.querySelector('a[href="/logout/"]');
            return logoutButton !== null;
        }''')

        return is_logged_in

    except Exception as e:
        print(f'{serviceName} 账号 {username} 登录时出现错误: {e}')
        return False

    finally:
        if page:
            await page.close()

async def shutdown_browser():
    """关闭浏览器"""
    global browser
    if browser:
        await browser.close()
        browser = None

async def main():
    """主逻辑"""
    global message

    try:
        async with aiofiles.open('accounts.json', mode='r', encoding='utf-8') as f:
            accounts_json = await f.read()
        accounts = json.loads(accounts_json)
    except Exception as e:
        print(f'读取 accounts.json 文件时出错: {e}')
        return

    for account in accounts:
        username = account['username']
        password = account['password']
        panel = account['panel']

        serviceName = get_service_name(panel)  # 自动匹配 panel 对应名称
        is_logged_in = await login(username, password, panel)

        now_beijing = format_to_iso(datetime.utcnow() + timedelta(hours=8))
        if is_logged_in:
            message += f"✅ *{serviceName}* 账号 *{username}* 于北京时间 {now_beijing} 登录成功！\n\n"
            print(f"{serviceName} 账号 {username} 于北京时间 {now_beijing} 登录成功！")
        else:
            message += f"❌ *{serviceName}* 账号 *{username}* 于北京时间 {now_beijing} 登录失败\n\n❗请检查 *{username}* 账号和密码是否正确。\n\n"
            print(f"{serviceName} 账号 {username} 登录失败，请检查账号和密码是否正确。")

        delay = random.randint(1000, 8000)
        await delay_time(delay)
        
    message += f"🔚 脚本结束，如有异常点击下方按钮👇"
    await send_telegram_message(message)
    print(f'所有账号登录完成！')

    # 退出时关闭浏览器
    await shutdown_browser()

async def send_telegram_message(message):
    """发送 Telegram 通知"""
    formatted_message = f"""
*🎯 serv00&ct8 自动化保号脚本运行报告*

🕰 *北京时间*: {format_to_iso(datetime.utcnow() + timedelta(hours=8))}

⏰ *UTC 时间*: {format_to_iso(datetime.utcnow())}

📝 *任务报告*:

{message}
    """

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': formatted_message,
        'parse_mode': 'Markdown',  # 使用 Markdown 格式
        'reply_markup': {
            'inline_keyboard': [
                [
                    {
                        'text': '问题反馈❓',
                        'url': 'https://t.me/yxjsjl'  # 点击按钮后跳转到问题反馈的链接
                    }
                ]
            ]
        }
    }
    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"发送消息到 Telegram 失败: {response.text}")
    except Exception as e:
        print(f"发送消息到 Telegram 时出错: {e}")

if __name__ == '__main__':
    asyncio.run(main())
