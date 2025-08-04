import requests

def download_font(url, save_path="temp/font.ttf"):
    response = requests.get(url)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            f.write(response.content)
        print("✅ Font downloaded")
    else:
        raise Exception("⚠️ Failed to download font")
