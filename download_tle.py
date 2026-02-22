import urllib.request
import urllib.error
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
urls = [
    'https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle',
    'https://celestrak.com/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle'
]

for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
            with open('visual.txt', 'wb') as f:
                f.write(response.read())
        print(f"Successfully downloaded from {url}")
        break
    except Exception as e:
        print(f"Failed to download from {url}: {e}")
