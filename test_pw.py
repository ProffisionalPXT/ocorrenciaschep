import asyncio, os
from playwright.async_api import async_playwright

async def run():
    p = await async_playwright().start()
    user_data_dir = os.path.join(os.path.expanduser("~"), ".chep_bot_chrome_profile_purm2")
    
    try:
        ctx = await p.chromium.launch_persistent_context(user_data_dir, headless=False, no_viewport=True)
        print("Pages:", len(ctx.pages))
        await asyncio.sleep(2)
        await ctx.close()
    except Exception as e:
        print("ERROR:", e)
        
    p.stop()

asyncio.run(run())
