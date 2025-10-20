import json
import asyncio
from pyppeteer import launch, errors
from datetime import datetime, timedelta
import aiofiles
import random
import requests
import os
import traceback

# 环境变量
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def format_to_iso(date):
    return date.strftime('%Y-%m-%d %H:%M:%S')

async def delay_time(ms):
    await asyncio.sleep(ms / 1000)

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
        except Exception:
            return 'Unknown'
    return 'Unknown'

async def robust_click(page, selector):
    """
    尝试多种方式点击 selector:
    1) 等待可见，scrollIntoView + element.click()（在页面上下文调用）
    2) page.click(selector)（pyppeteer 自带方法）
    3) 在 password 输入上按 Enter（回车提交）
    4) 尝试 form.submit()（如果元素在表单内）
    如果成功返回 True，否则 False。
    """
    try:
        # 1) 等待并在页面上下文点击
        await page.waitForSelector(selector, timeout=10000, visible=True)
        el = await page.querySelector(selector)
        if el:
            try:
                # 把元素滚动到视口中心并在 DOM 上点击
                await page.evaluate('(el) => { el.scrollIntoView({behavior:"instant", block:"center"}); }', el)
                await page.evaluate('(el) => el.click()', el)
                return True
            except Exception as e:
                # 记录并继续尝试
                print(f"page.evaluate click failed: {e}")
    except Exception as e:
        print(f"等待 selector {selector} 可见失败: {e}")

    # 2) 尝试 page.click（pyppeteer 方法）
    try:
        await page.click(selector, timeout=5000)
        return True
    except Exception as e:
        print(f"page.click 失败: {e}")

    # 3) 按 Enter 提交（在密码输入框上）
    try:
        if await page.querySelector('#id_password'):
            await page.focus('#id_password')
            await page.keyboard.press('Enter')
            return True
    except Exception as e:
        print(f"回车提交失败: {e}")

    # 4) 尝试找到包含输入的 form 并调用 submit()
    try:
        has_form = await page.evaluate('''() => {
            const input = document.querySelector('#id_username') || document.querySelector('#id_password');
            if (!input) return false;
            const form = input.closest('form');
            if (!form) return false;
            form.submit();
            return true;
        }''')
        if has_form:
            return True
    except Exception as e:
        print(f"form.submit() 失败: {e}")

    return False

async def login(username, password, panel):
    global browser
    page = None
    service_name = get_service_name(panel)

    try:
        if not browser:
            browser = await launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])

        page = await browser.newPage()
        url_https = f'https://{panel}/login/'
        url_http = f'http://{panel}/login/'

        # 尝试 HTTPS，然后回退到 HTTP
        try:
            await page.goto(url_https, timeout=20000)
        except Exception as e:
            print(f"{service_name}: HTTPS 打开失败 ({e})，尝试 HTTP...")
            try:
                await page.goto(url_http, timeout=20000)
            except Exception as e2:
                print(f"{service_name}: HTTP 打开也失败: {e2}")
                return False

        # 等待用户名和密码字段出现（可见或不可见）
        try:
            await page.waitForSelector('#id_username', timeout=10000)
            await page.waitForSelector('#id_password', timeout=10000)
        except Exception as e:
            print(f"{service_name}: 未检测到用户名或密码输入框: {e}")
            # 仍继续尝试后续步骤以获得更多日志
        # 清空并输入
        try:
            await page.evaluate('''() => { const u = document.querySelector('#id_username'); if (u) u.value=''; }''')
            await page.type('#id_username', username, {'delay': 50})
            await page.type('#id_password', password, {'delay': 50})
        except Exception as e:
            print(f"{service_name}: 填写用户名/密码出错: {e}")

        # 多种方式尝试提交登录
        clicked = await robust_click(page, 'button.button--primary')

        if not clicked:
            print(f"{service_name}: 所有点击/提交尝试失败，继续等待并检查页面内容以便诊断。")

        # 登录后给页面一点时间处理 AJAX
        await page.waitForTimeout(4000)

        # 检查是否登录成功：查找常见关键词或 logout 链接
        try:
            page_text = await page.evaluate('() => document.body.innerText || document.documentElement.innerText')
        except Exception:
            page_text = ''
        success_keywords = ['Wyloguj', 'Wyloguj się', 'Logout', 'Wylogowanie', 'Panel użytkownika', 'dashboard', 'Moje konto', 'wyloguj']
        is_logged_in = any(k.lower() in (page_text or '').lower() for k in success_keywords)

        # 备用：检测 URL 变化（有些站点提交后会跳转）
        try:
            current_url = page.url
            if '/panel' in current_url or '/dashboard' in current_url:
                is_logged_in = True
        except Exception:
            current_url = None

        # 另一个备用：检测 cookie（例如带有 sessionid 的 cookie）
        # 这里只是示例，不强制要求
        try:
            cookies = await page.cookies()
            # 若有明显的会话 cookie（依据实际站点而定）
            if any('session' in c['name'].lower() or 'sid' in c['name'].lower() for c in cookies):
                # 不覆盖已检测到的登录成功，但作为佐证
                print(f"{service_name}: 检测到 session cookie: {[c['name'] for c in cookies]}")
        except Exception:
            pass

        return is_logged_in

    except Exception as e:
        print(f"{service_name}账号 {username} 登录错误: {e}")
        traceback.print_exc()
        return False

    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass

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
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"发送消息到 Telegram 失败: {response.text}")
    except Exception as e:
        print(f"发送消息到 Telegram 时出错: {e}")

async def main():
    global message, login_results
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

        delay = random.randint(1000, 6000)
        await delay_time(delay)

    message += "\n🔚 登录结束，失败账号统计如下：\n"
    for service, results in login_results.items():
        if results['fail']:
            message += f"📦 *{service}* 登录失败账号数: {len(results['fail'])} 个，分别是: {', '.join(results['fail'])}\n"

    await send_telegram_message(message)
    print("所有账号登录任务完成 ✅")
    await shutdown_browser()

if __name__ == '__main__':
    asyncio.run(main())
