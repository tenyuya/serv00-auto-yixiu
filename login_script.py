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

# telegram消息
message = ""

# 用于存储各个服务成功与失败的账号
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
    global browser

    page = None
    service_name = get_service_name(panel)
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
        print(f'{service_name}账号 {username} 登录时出现错误: {e}')
        return False

    finally:
        if page:
            await page.close()

async def shutdown_browser():
    global browser
    if browser:
        await browser.close()
        browser = None

async def main():
    global message, login_results

    try:
        async with aiofiles.open('accounts.json', mode='r', encoding='utf-8') as f:
            accounts_json = await f.read()
        accounts = json.loads(accounts_json)
    except Exception as e:
        print(f'读取 accounts.json 文件时出错: {e}')
        return

    # 统计账号和封禁信息
    ct8_total = 0
    ct8_fail_count = 0

    for account in accounts:
        username = account['username']
        password = account['password']
        panel = account['panel']

        service_name = get_service_name(panel)
        is_logged_in = await login(username, password, panel)

        now_beijing = format_to_iso(datetime.utcnow() + timedelta(hours=8))

        # 统计成功和失败的账号
        if service_name not in login_results:
            login_results[service_name] = {'success': [], 'fail': []}

        if service_name == 'CT8':
            ct8_total += 1  # 统计CT8账号数量

        if is_logged_in:
            login_results[service_name]['success'].append(username)
            print(f"{service_name}账号 {username} 于北京时间 {now_beijing} 登录面板成功！")
        else:
            login_results[service_name]['fail'].append(username)
            if service_name == 'CT8':
                ct8_fail_count += 1  # 统计CT8账号失败数量
            # 记录失败账号并展示
            message += f"❌*{service_name}*账号 *{username}* 于北京时间 {now_beijing} 登录失败\n\n❗️您的账号已被封禁！\n\n"
            print(f"{service_name}账号 {username} 登录失败，账号已被封禁。")

        delay = random.randint(1000, 8000)
        await delay_time(delay)

    # 生成统计信息
    message = f"""
*🎯 serv00&ct8自动化保号脚本运行报告*

🕰 *北京时间*: {format_to_iso(datetime.utcnow() + timedelta(hours=8))}

⏰ *UTC时间*: {format_to_iso(datetime.utcnow())}

📝 *任务报告*:

📊 *统计信息*：
- CT8 总账号数: {ct8_total} 个
- 今日被封禁的账号数: {ct8_fail_count} 个

"""

    # 删除之前的登录成功和失败的详情，只保留失败账户统计
    message += "\n🔚脚本结束，失败账户统计如下：\n"
    
    # 只统计登录失败的 CT8 账号
    if 'CT8' in login_results:
        ct8_fail_accounts = login_results['CT8']['fail']
        if ct8_fail_accounts:
            # 如果有失败的CT8账号，列出详细的失败账号
            for fail_account in ct8_fail_accounts:
                message += f"❌*CT8*账号 *{fail_account}* 于北京时间 {now_beijing} 登录失败\n\n❗️您的账号已被封禁！\n\n"
    
    # 其他服务的失败账号
    for service, results in login_results.items():
        if service != 'CT8' and results['fail']:
            for fail_account in results['fail']:
                message += f"❌*{service}*账号 *{fail_account}* 于北京时间 {now_beijing} 登录失败\n\n❗️您的账号已被封禁！\n\n"

    await send_telegram_message(message)
    print(f'所有账号登录完成！')
    await shutdown_browser()

async def send_telegram_message(message):
    formatted_message = f"""
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

if __name__ == '__main__':
    asyncio.run(main())
