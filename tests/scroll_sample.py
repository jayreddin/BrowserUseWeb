import sys,os,time

from playwright.sync_api import sync_playwright

def scroll_page(amount: int):
    with sync_playwright() as p:
        #browser = p.chromium.launch(headless=False)  # GUIを表示する場合は headless=False
        browser = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=False)
        page = browser.new_page()
        page_html = "tests/scroll_gide.html"
        full_path = os.path.abspath(page_html)
        page.goto(f"file://{full_path}")  # 任意のURLに変更
        
        step = 100
        time.sleep( 2.0 )
        for i in range(0,20):
            # 指定したピクセル量だけスクロール
            print(f"scrolling {i} {step} pixels")
            page.evaluate(f'window.scrollBy(0, {step});')
            # 現在のスクロール量を取得
            scroll_position = page.evaluate('window.scrollY')
            print(f"現在のスクロール位置: {scroll_position}px {type(scroll_position)}")
            # しばらく待機してスクロールを確認
            page.wait_for_timeout(2000)
            # time.sleep( 1.0 )
        print("scrolling done")
        time.sleep( 20.0 )
        browser.close()

if __name__ == "__main__":
    scroll_page(500)  # 500pxスクロール
