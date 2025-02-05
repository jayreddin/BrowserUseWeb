import sys,os,time
import re
import asyncio
from urllib.parse import urlparse

from playwright.async_api import async_playwright
from playwright.async_api._generated import Page, Frame
from playwright.async_api import TimeoutError

# 広告系のホスト名パターン（正規表現リスト）
AD_HOST_PATTERNS = [
    r"\btrack\b", r"\btracking\b", # 単語 track
    r"click",       # 単語 click
    r"\bmetrics\b",     # 単語 metrics
    r"\bad\b",          # 単語 ad
    r"\bads\b",         # 単語 ads
    r"apm.yahoo.co.jp", 
    r"taboola.com",
    r"g2afse.com",
    r"hubs.li",
    r"graxis.jp",
    r"apm.yahoo.co.jp",
]

def add_test():

    hostname_list = [ "tenki.jp", "", "nexters.g2afse.com", "popup.taboola.com", "callofwar.com", "5minstory.com", "track.constant-track.com", "localplan.co", "search.goodfavornews.com", "info.wwwad17.mitsubishielectric.co.jp", "social-innovation.hitachi", "jp.wwiqtest.com", "trck.tracking505.com", "kingdomofmen.com", "hubs.li", "x.com", "twitter.com", "youtube.com", "facebook.com", "instagram.com", "jwa.or.jp", "alink.ne.jp", "config.tenki.jp" ]
    for hostname in hostname_list:
        is_add = any(re.search(pattern, hostname) for pattern in AD_HOST_PATTERNS)
        print( f"{hostname} {is_add}")

async def get_links(target:Page|Frame,list:set):
    try:
        #print(f"get links {type(target)}")
        js = """() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"""
        links = await target.evaluate(js)
        for link in links:
            list.add(link)
    except Exception as ex:
        print(f"ERROR: get_links {ex}")

async def add_cleaner(page:Page):
        linkset:set = set()
        await get_links(page,linkset)
        frames = page.frames
        for frame in frames:
            await get_links(frame,linkset)
        #print("Found anchor URLs:")
        hostmap = {}
        add_url_list = {}
        jslist = []
        jslist.append('(() => {')
        for link in linkset:
            par = urlparse(link)
            hostname = par.netloc.lstrip("www.")
            if hostname:
                is_add = any(re.search(pattern, hostname) for pattern in AD_HOST_PATTERNS)
                if is_add:
                    jslist.append( f"""  document.querySelectorAll('a[href="{link}"]').forEach(a => a.remove());""" )
                    add_url_list[link]=is_add
                print( f"{hostname} {is_add} {link}")
                hostmap[hostname]=is_add
        jslist.append('})();')
        #print("Found hostnames:")
        #sample_code = ', '.join([ f'"{h}"' for h in hostmap.keys()])
        #print( f"urls = [ {sample_code} ]" )

        js = '\n'.join(jslist)
        #print(js)
        print(f"remove links in page")
        await page.evaluate(js)
        for frame in frames:
            print(f"remove links frame")
            await frame.evaluate(js)
        print("Done")

async def scroll_page():
    chrome_path_list = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/opt/google/chrome/google-chrome"
    ]
    chrome_path = None
    for aaa in chrome_path_list:
        if os.path.exists(aaa):
            chrome_path = aaa
            break
    if chrome_path is None:
        raise ValueError("chromeがみつからない")

    async with async_playwright() as p:
        #browser = p.chromium.launch(headless=False)  # GUIを表示する場合は headless=False
        browser = await p.chromium.launch(executable_path=chrome_path, headless=False)
        page = await browser.new_page()
        print(f"{type(page)}")
        page_html = "tests/scroll_gide.html"
        full_path = os.path.abspath(page_html)
        url = f"file://{full_path}"
        url = "https://tenki.jp/forecast/6/29/6110/26100/"
        url = "https://news.goo.ne.jp/"

        try:
            await page.goto(url,timeout=30000.0, wait_until='domcontentloaded' )  # 任意のURLに変更
            await page.wait_for_timeout(1000)
        except TimeoutError as ex:
            print(ex)
        
        #await add_cleaner(page)
        content_html = await page.content()
        os.makedirs("tmp",exist_ok=True)
        with open("tmp/content_orig.html","w") as f:
            f.write( content_html )
        import markdownify
        content_md = markdownify.markdownify(content_html)
        with open("tmp/content_orig.md","w") as f:
            f.write( content_md )

        step = 300
        time.sleep( 2.0 )
        for i in range(0,20):
            #await add_cleaner(page)
            # 指定したピクセル量だけスクロール
            print(f"scrolling {i} {step} pixels")
            await page.evaluate(f'window.scrollBy(0, {step});')
            # 現在のスクロール量を取得
            scroll_position = await page.evaluate('window.scrollY')
            print(f"現在のスクロール位置: {scroll_position}px {type(scroll_position)}")
            # しばらく待機してスクロールを確認
            await page.wait_for_timeout(2000)
            # time.sleep( 1.0 )
        print("scrolling done")
        time.sleep( 20.0 )
        await browser.close()

def main():
    #add_test()
    asyncio.run(scroll_page())

if __name__ == "__main__":
    main()
