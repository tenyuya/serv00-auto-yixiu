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
    if 'ct8' in panel.lower():
        return 'CT8'
    elif 'panel' in panel.lower():
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
    screenshot_path = f"error_{service_name}_{username}.png"  # 错误截图路径

    try:
        if not browser:
            browser = await launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'  # 伪装 Chrome
                ]
            )

        page = await browser.newPage()
        # 隐藏 webdriver 属性
        await page.evaluateOnNewDocument('''() => {
            Object.defineProperty(navigator, "webdriver", { get: () => undefined });
        }''')

        url = f'https://{panel}/login/?next=/'
        await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 30000})  # 等待网络空闲，超时 30s

        # 通用用户名选择器（支持 id 或 name）
        username_selectors = ['#id_username', '#username', 'input[name="username"]', 'input[name="login"]']
        username_input = None
        for selector in username_selectors:
            username_input = await page.querySelector(selector)
            if username_input:
                break
        if not username_input:
            raise Exception('无法找到用户名输入框')

        # 清空并输入用户名
        await page.evaluate('input => input.value = ""', username_input)
        await page.type(selector, username, {'delay': random.randint(50, 150)})  # 模拟打字延时

        # 通用密码选择器
        password_selectors = ['#id_password', '#password', 'input[name="password"]', 'input[type="password"]']
        password_input = None
        for selector in password_selectors:
            password_input = await page.querySelector(selector)
            if password_input:
                break
        if not password_input:
            raise Exception('无法找到密码输入框')

        await page.type(selector, password, {'delay': random.randint(50, 150)})

        # 通用提交按钮选择器
        submit_selectors = ['#submit', 'button[type="submit"]', 'input[type="submit"]', '.btn-login', 'button:contains("Log in")']
        submit_button = None
        for selector in submit_selectors:
            try:
                submit_button = await page.querySelector(selector)
                if submit_button:
                    break
            except:
                continue
        if not submit_button:
            raise Exception('无法找到登录按钮')

        # 点击前等待
        await page.waitFor(1000 + random.randint(0, 500))

        await submit_button.click()

        # 改进导航等待：等待 URL 变化或特定元素
        try:
            await page.waitForNavigation({'waitUntil': 'networkidle2', 'timeout': 10000})
        except:
            # 如果无导航，等待 5s
            await asyncio.sleep(5)

        # 改进登录成功检查：多条件（logout 链接或 dashboard 元素）
        is_logged_in = await page.evaluate('''() => {
            const logoutButton = document.querySelector('a[href="/logout/"], a[href*="logout"]');
            const dashboard = document.querySelector('h1, .dashboard, [class*="welcome"]');  // 常见 dashboard 标志
            return logoutButton !== null || dashboard !== null;
        }''')

        if not is_logged_in:
            # 保存截图调试
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
            print(f"登录失败，截图保存至 {screenshot_path}")

        return is_logged_in

    except Exception as e:
        # 错误时也截图
        if page:
            await page.screenshot({'path': screenshot_path, 'fullPage': True})
        print(f'{service_name}账号 {username} 登录时出现错误: {e}')
        print(f"错误截图: {screenshot_path}")
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

    for account in accounts:
        username = account['username']
        password = account['password']
        panel = account['panel']

        service_name = get_service_name(panel)
        is_logged_in = await login(username, password, panel)

        now_beijing = format_to_iso(datetime.utcnow() + timedelta(hours=8))

        if service_name not in login_results:
            login_results[service_name] = {'success': [], 'fail': []}

        if is_logged_in:
            login_results[service_name]['success'].append(username)
            message += f"✅*{service_name}*账号 *{username}* 于北京时间 {now_beijing} 登录面板成功！\n\n"
            print(f"{service_name}账号 {username} 于北京时间 {now_beijing} 登录面板成功！")
        else:
            login_results[service_name]['fail'].append(username)
            message += f"❌*{service_name}*账号 *{username}* 于北京时间 {now_beijing} 登录失败\n\n❗请检查 *{username}* 账号和密码是否正确。\n\n"
            print(f"{service_name}账号 {username} 登录失败，请检查 {service_name} 账号和密码是否正确。")

        delay = random.randint(3000, 10000)  # 延时稍长，避免频繁请求被限
        await delay_time(delay)

    # 报告优化：添加成功统计
    message += "\n🔚脚本结束，登录统计如下：\n"
    total_success = sum(len(r['success']) for r in login_results.values())
    total_fail = sum(len(r['fail']) for r in login_results.values())
    message += f"📊 总成功: {total_success} 个，总失败: {total_fail} 个\n\n"
    for service, results in login_results.items():
        if results['fail']:
            message += f"📦 *{service}* 登录失败账户数: {len(results['fail'])} 个，分别是: {', '.join(results['fail'])}\n"
        if results['success']:
            message += f"✅ *{service}* 登录成功账户数: {len(results['success'])} 个\n"

    await send_telegram_message(message)
    print(f'所有账号登录完成！总成功: {total_success}, 总失败: {total_fail}')
    await shutdown_browser()

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

if __name__ == '__main__':
    asyncio.run(main())
