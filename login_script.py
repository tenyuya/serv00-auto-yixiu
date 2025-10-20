import json
import asyncio
from pyppeteer import launch
from datetime import datetime, timedelta
import aiofiles
import random
import requests
import os

# 从环境变量中获取 Telegram Bot Token 和 Chat ID
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def format_to_iso(date):
    return date.strftime('%Y-%m-%d %H:%M:%S')

async def delay_time(ms):
    await asyncio.sleep(ms / 1000)

# 全局浏览器实例
browser = None
message = ""
login_results = {}

def get_service_name(panel):
    if 'ct8' in panel:
        return 'CT8'
    elif 'panel' in panel:
        try:
            panel_number = int(panel.split('panel')[1].split('.')[0])
            return f'S{panel_number}'
        except ValueError:
            return 'Unknown'
    return 'Unknown'


async def login(username, password, panel):
    """
    登录新版 serv00/ct8 面板
    新版页面结构已更新：
    - 用户名输入框：#id_username
    - 密码输入框：#id_password
    - 登录按钮：button.button--primary
    登录成功后页面不会重定向，需检测“Wyloguj”或“logout”关键字。
    """
    global browser
    page = None
    service_name = get_service_name(panel)

    try:
        # 若浏览器未启动，则启动
        if not browser:
            browser = await launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )

        page = await browser.newPage()
        url_https = f'https://{panel}/login/'
        url_http = f'http://{panel}/login/'

        # 优先尝试 HTTPS，失败再尝试 HTTP
        try:
            await page.goto(url_https, timeout=15000)
        except Exception:
            print(f"{service_name}: HTTPS 访问失败，尝试 HTTP...")
            await page.goto(url_http, timeout=15000)

        # 填写账号密码
        await page.waitForSelector('#id_username', timeout=10000)
        await page.evaluate('''() => document.querySelector('#id_username').value = '' ''')
        await page.type('#id_username', username, {'delay': 50})
        await page.type('#id_password', password, {'delay': 50})

        # 点击登录按钮
        login_button = await page.querySelector('button.button--primary')
        if not login_button:
            raise Exception("未找到登录按钮 .button--primary")

        await login_button.click()

        # 等待登录完成：新版网站可能不会跳转，因此等待页面内容变化
        await page.waitForTimeout(4000)

        # 判断是否登录成功
        page_text = await page.content()
        success_keywords = ['Wyloguj', 'logout', 'Panel użytkownika', 'dashboard']
        is_logged_in = any(keyword.lower() in page_text.lower() for keyword in success_keywords)

        return is_logged_in

    except Exception as e:
        print(f"{service_name}账号 {username} 登录错误: {e}")
        return False

    finally:
        if page:
            await page.close()


async def shutdown_browser():
    global browser
    if browser:
        await browser.close()
        browser = None


async def send_telegram_message(message):
    formatted_message = f"""
*🎯 serv00&ct8自动化保号脚本运行报告*

🕰 *北京时间*: {format_to_iso(datetime.utcnow() + timedelta(hours=8))}
⏰ *UTC时间*: {format_to_iso(datetime.utcnow())}

📝 *任务报告*:

{message}
"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': formatted_message,
        'parse_mode': 'Markdown'
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"发送消息到 Telegram 失败: {response.text}")
    except Exception as e:
        print(f"发送消息到 Telegram 时出错: {e}")


async def main():
    global message, login_results

    # 读取账号文件
    try:
        async with aiofiles.open('accounts.json', mode='r', encoding='utf-8') as f:
            accounts_json = await f.read()
        accounts = json.loads(accounts_json)
    except Exception as e:
        print(f'读取 accounts.json 文件出错: {e}')
        return

    for account in accounts:
        username = account['username']
        password = account['password']
        panel = account['panel']

        service_name = get_service_name(panel)
        now_beijing = format_to_iso(datetime.utcnow() + timedelta(hours=8))

        print(f"开始登录 {service_name} - {username} ...")
        is_logged_in = await login(username, password, panel)

        if service_name not in login_results:
            login_results[service_name] = {'success': [], 'fail': []}

        if is_logged_in:
            login_results[service_name]['success'].append(username)
            msg = f"✅ *{service_name}* 账号 *{username}* 于北京时间 {now_beijing} 登录成功！\n"
            message += msg + "\n"
            print(msg)
        else:
            login_results[service_name]['fail'].append(username)
            msg = f"❌ *{service_name}* 账号 *{username}* 于北京时间 {now_beijing} 登录失败。\n"
            message += msg + "\n"
            print(msg)

        # 每次登录间隔随机延迟
        delay = random.randint(1000, 6000)
        await delay_time(delay)

    # 统计汇总
    message += "\n🔚 登录结束，失败账号统计如下：\n"
    for service, results in login_results.items():
        if results['fail']:
            message += f"📦 *{service}* 登录失败账号数: {len(results['fail'])} 个，分别是: {', '.join(results['fail'])}\n"

    await send_telegram_message(message)
    print("所有账号登录任务完成 ✅")
    await shutdown_browser()


if __name__ == '__main__':
    asyncio.run(main())
