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
    screenshot_path_before = f"before_{service_name}_{username}.png"
    screenshot_path_after = f"after_{service_name}_{username}.png"
    debug_html_path = f"debug_{service_name}_{username}.html"

    try:
        if not browser:
            browser = await launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-web-security',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ],
                defaultViewport=None
            )

        page = await browser.newPage()
        await page.evaluateOnNewDocument('''() => {
            Object.defineProperty(navigator, "webdriver", { get: () => undefined });
        }''')

        url = f'https://{panel}/login/?next=/'
        await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 45000})

        await delay_time(3000 + random.randint(0, 2000))

        await page.screenshot({'path': screenshot_path_before, 'fullPage': True})
        print(f"前状态截图: {screenshot_path_before}")

        # 用户名
        username_selectors = ['#id_username', 'input[name="username"]']
        username_input = None
        username_selector = None
        for sel in username_selectors:
            try:
                await page.waitForSelector(sel, {'timeout': 10000})
                username_input = await page.querySelector(sel)
                if username_input:
                    username_selector = sel
                    print(f"用户名输入框找到: {sel}")
                    break
            except:
                continue
        if not username_input:
            raise Exception('无法找到用户名输入框')

        await page.evaluate('el => el.scrollIntoView({behavior: "smooth", block: "center"})', username_input)
        await delay_time(500)

        await page.evaluate('''(el, val) => {
            el.focus();
            el.value = "";
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.blur();  // 新: 触发 blur 验证
            console.log("用户名设置: " + val);
        }''', username_input, username)

        # 密码
        password_selectors = ['#id_password', 'input[name="password"]', 'input[type="password"]']
        password_input = None
        password_selector = None
        for sel in password_selectors:
            try:
                await page.waitForSelector(sel, {'timeout': 10000})
                password_input = await page.querySelector(sel)
                if password_input:
                    password_selector = sel
                    print(f"密码输入框找到: {sel}")
                    break
            except:
                continue
        if not password_input:
            raise Exception('无法找到密码输入框')

        await page.evaluate('el => el.scrollIntoView({behavior: "smooth", block: "center"})', password_input)
        await delay_time(500)

        await page.evaluate('''(el, val) => {
            el.focus();
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.blur();  // 新: 触发 blur
            console.log("密码设置完成");
        }''', password_input, password)

        # 提交按钮
        submit_selectors = [
            'button[type="submit"]',
            '.button--primary',
            '.login-form__button button[type="submit"]',
            'button:has(span)'
        ]
        submit_button = None
        submit_selector = None
        for sel in submit_selectors:
            try:
                await page.waitForSelector(sel, {'timeout': 15000})
                submit_button = await page.querySelector(sel)
                if submit_button:
                    submit_selector = sel
                    print(f"✅ 找到按钮 (选择器: {sel})")
                    break
            except Exception as sel_err:
                print(f"选择器 {sel} 超时/失败: {sel_err}")

        if not submit_button:
            all_buttons = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('button, input[type="submit"]')).map(b => b.outerHTML.substring(0, 200) + '...');
            }''')
            print(f"页面所有 buttons: {all_buttons}")
            
            html_content = await page.content()
            async with aiofiles.open(debug_html_path, 'w', encoding='utf-8') as f:
                await f.write(html_content)
            print(f"按钮未找到，HTML 保存至: {debug_html_path}")

            await page.evaluate('''() => {
                const form = document.querySelector('form');
                if (form) form.submit();
            }''')
            print("🔄 备用: 直接提交表单")
        else:
            await page.evaluate('el => el.scrollIntoView({behavior: "smooth", block: "center"})', submit_button)
            await delay_time(1500 + random.randint(0, 1000))

            try:
                await page.click(submit_selector, {'force': True, 'delay': random.randint(100, 300)})
                print("✅ 使用 page.click 提交")
            except:
                await page.evaluate('''(el) => {
                    el.focus();
                    el.click();
                    el.dispatchEvent(new Event('click', { bubbles: true }));
                    el.dispatchEvent(new Event('submit', { bubbles: true }));
                    console.log("备用 JS 点击按钮");
                }''', submit_button)
                print("✅ 使用 JS evaluate 点击")

        # 新: AJAX 等待（无 navigation， 等动态更新 10s）
        await delay_time(10000)  # 延长等错误/成功加载
        print("⏳ AJAX 等待完成，检查状态")

        await page.screenshot({'path': screenshot_path_after, 'fullPage': True})
        print(f"后状态截图: {screenshot_path_after}")

        # URL 检查（AJAX 可能不变）
        current_url = page.url
        print(f"当前 URL: {current_url} (AJAX 可能不变)")

        # 强化错误检测（更多匹配）
        error_check = await page.evaluate('''() => {
            const errorSelectors = '.alert-danger, .alert-error, .alert, [class*="alert"][class*="danger"], [class*="error"], [class*="invalid"], [class*="wrong"], div[style*="color: red"]';
            const errorEl = document.querySelector(errorSelectors);
            let errorText = '';
            if (errorEl) {
                errorText = errorEl.textContent.trim() || errorEl.innerText.trim();
            }
            // 文本匹配
            const hasErrorText = errorText.toLowerCase().includes('nieprawidłowe') || 
                                 errorText.toLowerCase().includes('błędne') ||
                                 errorText.toLowerCase().includes('invalid') ||
                                 errorText.toLowerCase().includes('wrong') ||
                                 errorText.toLowerCase().includes('error') ||
                                 errorText.length > 10;  // 任意长文本
            return {hasError: !!errorEl && hasErrorText, errorText: errorText};
        }''')
        print(f"错误检查: {error_check}")

        # 成功 DOM 检查
        success_check = await page.evaluate('''() => {
            const logoutButton = document.querySelector('a[href="/logout/"], a[href*="logout"], [class*="logout"]');
            const dashboard = document.querySelector('.dashboard, [class*="user-panel"], [class*="welcome-user"], h1:not(.login-title), main:not(.login-main)');
            const successMsg = document.querySelector('[class*="success"], .alert-success');
            return {hasLogout: !!logoutButton, hasDashboard: !!dashboard, hasSuccess: !!successMsg};
        }''')
        print(f"成功检查: {success_check}")

        # 最终判断
        has_error = error_check['hasError']
        has_success = success_check['hasLogout'] or success_check['hasDashboard'] or success_check['hasSuccess']
        is_logged_in = has_success and not has_error

        if has_error:
            print(f"❌ 错误提示: {error_check['errorText']}（密码/账号问题）")
        elif has_success:
            print("✅ DOM 检查: 登录成功（AJAX 更新）")
        else:
            print("❌ 无重定向/成功元素/错误 - 手动查密码/IP")

        if not is_logged_in:
            print(f"登录失败 - 查看 {screenshot_path_after}")
            html_content = await page.content()
            async with aiofiles.open(debug_html_path, 'w', encoding='utf-8') as f:
                await f.write(html_content)
            print(f"后状态 HTML: {debug_html_path}")

        return is_logged_in

    except Exception as e:
        if page:
            await page.screenshot({'path': screenshot_path_after, 'fullPage': True})
            html_content = await page.content()
            async with aiofiles.open(debug_html_path, 'w', encoding='utf-8') as f:
                await f.write(html_content)
            print(f"错误 HTML: {debug_html_path}")
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

        delay = random.randint(3000, 10000)
        await delay_time(delay)

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
