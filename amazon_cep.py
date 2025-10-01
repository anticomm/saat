import os
import json
import time
import base64
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from telegram_cep import send_message

URL = "https://www.amazon.com.tr/s?k=ak%C4%B1ll%C4%B1+saat&i=warehouse-deals&bbn=44219324031&rh=n%3A44219324031%2Cn%3A13709898031%2Cp_98%3A21345978031%2Cp_123%3A110955%257C32374%257C338933%257C46655&dc&ds=v1%3Awlj0iR0TEz2KdzfNRsfdKwPXrK9koMXddqQ7HLFFDA8"
COOKIE_FILE = "cookie_cep.json"
SENT_FILE = "send_products.txt"

def decode_cookie_from_env():
    cookie_b64 = os.getenv("COOKIE_B64")
    if not cookie_b64:
        print("❌ COOKIE_B64 bulunamadı.")
        return False
    try:
        decoded = base64.b64decode(cookie_b64)
        with open(COOKIE_FILE, "wb") as f:
            f.write(decoded)
        print("✅ Cookie dosyası oluşturuldu.")
        return True
    except Exception as e:
        print(f"❌ Cookie decode hatası: {e}")
        return False

def load_cookies(driver):
    if not os.path.exists(COOKIE_FILE):
        print("❌ Cookie dosyası eksik.")
        return
    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    for cookie in cookies:
        try:
            driver.add_cookie({
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie.get("path", "/")
            })
        except Exception as e:
            print(f"⚠️ Cookie eklenemedi: {cookie.get('name')} → {e}")

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/115 Safari/537.36")
    options.page_load_strategy = 'eager'

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(60)
    return driver

def extract_price_from_selectors(driver_or_item, selectors):
    for selector in selectors:
        try:
            elements = driver_or_item.find_elements(By.XPATH, ".//" + selector.replace(".", "").replace(" ", "//"))
            for el in elements:
                text = el.get_attribute("innerText") or el.text
                if not text:
                    continue
                text = text.replace("\xa0", " ").replace("TL", " TL").strip()
                text = re.sub(r"\s+", " ", text)

                if any(x in text.lower() for x in [
                    "puan", "teslimat", "sipariş", "beğenilen", "kargo", "teklif",
                    "bedeli", "indirim", "kupon", "kampanya", "ödül"
                ]):
                    continue

                if not re.search(r"\d{1,3}(\.\d{3})*,\d{2} TL", text):
                    continue

                try:
                    val = float(text.replace("TL", "").replace(".", "").replace(",", ".").strip())
                    if val < 500 or val > 100_000:
                        print(f"⚠️ Şüpheli fiyat dışlandı: {text}")
                        continue
                except:
                    continue

                return text
        except:
            continue
    return None

def get_offer_listing_link(driver):
    try:
        el = driver.find_element(By.XPATH, "//a[contains(@href, '/gp/offer-listing/')]")
        href = el.get_attribute("href")
        if href.startswith("/"):
            return "https://www.amazon.com.tr" + href
        return href
    except:
        return None

def get_used_price_if_available(driver):
    try:
        container = driver.find_element(
            By.XPATH,
            "//div[contains(@class, 'a-column') and .//span[contains(text(), 'İkinci El Ürün Satın Al:')]]"
        )
        price_element = container.find_element(By.CLASS_NAME, "offer-price")
        price = price_element.text.strip()
        print(f"📦 İkinci El Fiyat bulundu: {price}")
        return price
    except:
        print("⛔ İkinci El fiyat bloğu bulunamadı")
        return None

def get_final_price(driver, link):
    price_selectors_detail = [
        ".aok-offscreen",
        "span.a-size-base.a-color-price.offer-price.a-text-normal",
        "span.a-color-base",
        "span.a-price-whole"
    ]
    price_selectors_offer = [
        ".a-price .a-offscreen",
        "span.a-color-price",
        "span.a-price-whole"
    ]

    try:
        driver.execute_script("window.open('');")
        driver.switch_to.window(driver.window_handles[1])
        driver.get(link)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        time.sleep(2)
        driver.execute_script("""
          document.querySelectorAll("h2.a-carousel-heading").forEach(h => {
            let box = h.closest("div");
            if (box) box.remove();
          });
        """)
        price = extract_price_from_selectors(driver, price_selectors_detail)
        if price:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            return price

        offer_link = get_offer_listing_link(driver)
        if offer_link:
            driver.get(offer_link)
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            time.sleep(2)
            price = extract_price_from_selectors(driver, price_selectors_offer)
            if price:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                return price

        used_price = get_used_price_if_available(driver)
        if used_price:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
            return used_price

        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        return None
    except Exception as e:
        print(f"⚠️ Sekme fallback hatası: {e}")
        try:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        return None
def load_sent_data():
    data = {}
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|", 1)
                if len(parts) == 2:
                    asin, price = parts
                    data[asin.strip()] = price.strip()
    return data

def save_sent_data(updated_data):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        for asin, price in updated_data.items():
            f.write(f"{asin} | {price}\n")

def run():
    if not decode_cookie_from_env():
        return

    driver = get_driver()

    try:
        driver.get(URL)
    except Exception as e:
        print(f"⚠️ İlk sayfa yüklenemedi: {e}")
        driver.quit()
        return

    time.sleep(2)
    load_cookies(driver)

    try:
        driver.get(URL)
    except Exception as e:
        print(f"⚠️ Cookie sonrası sayfa yüklenemedi: {e}")
        driver.quit()
        return

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-component-type='s-search-result']"))
        )
    except:
        print("⚠️ Sayfa yüklenemedi.")
        driver.quit()
        return

    driver.execute_script("""
      document.querySelectorAll("h5.a-carousel-heading").forEach(h => {
        let box = h.closest("div");
        if (box) box.remove();
      });
    """)

    items = driver.find_elements(By.CSS_SELECTOR, "div[data-component-type='s-search-result']")
    print(f"🔍 {len(items)} ürün bulundu.")
    products = []
    for item in items:
        try:
            heading_check = item.find_elements(By.XPATH, ".//preceding::h5[contains(text(), 'Aradığınızı bulamadınız mı?')]")
            if heading_check:
                continue

            if item.find_elements(By.XPATH, ".//span[contains(text(), 'Sponsorlu')]"):
                continue

            asin = item.get_attribute("data-asin")
            if not asin:
                continue

            title = item.find_element(By.CSS_SELECTOR, "img.s-image").get_attribute("alt").strip()
            link = item.find_element(By.CSS_SELECTOR, "a.a-link-normal").get_attribute("href")
            image = item.find_element(By.CSS_SELECTOR, "img.s-image").get_attribute("src")

            price = extract_price_from_selectors(item, [
                ".a-price .a-offscreen",
                "span.a-color-base",
                "span.a-price-whole"
            ])

            if not price:
                price = get_final_price(driver, link)

            if not price:
                continue

            products.append({
                "asin": asin,
                "title": title,
                "link": link,
                "image": image,
                "price": price
            })

        except Exception as e:
            print(f"⚠️ Ürün parse hatası: {e}")
            continue

    driver.quit()
    print(f"✅ {len(products)} ürün başarıyla alındı.")

    sent_data = load_sent_data()
    products_to_send = []

    for product in products:
        asin = product["asin"]
        price = product["price"].strip()

        if asin in sent_data:
            old_price = sent_data[asin]
            try:
                old_val = float(old_price.replace("TL", "").replace(".", "").replace(",", ".").strip())
                new_val = float(price.replace("TL", "").replace(".", "").replace(",", ".").strip())
            except:
                print(f"⚠️ Fiyat karşılaştırılamadı: {product['title']} → {old_price} → {price}")
                sent_data[asin] = price
                continue

            if new_val < old_val:
                print(f"📉 Fiyat düştü: {product['title']} → {old_price} → {price}")
                product["old_price"] = old_price
                products_to_send.append(product)
            else:
                print(f"⏩ Fiyat yükseldi veya aynı: {product['title']} → {old_price} → {price}")
            sent_data[asin] = price

        else:
            print(f"🆕 Yeni ürün: {product['title']}")
            products_to_send.append(product)
            sent_data[asin] = price

    if products_to_send:
        for p in products_to_send:
            send_message(p)
        save_sent_data(sent_data)
        print(f"📁 Dosya güncellendi: {len(products_to_send)} ürün eklendi/güncellendi.")
    else:
        print("⚠️ Yeni veya indirimli ürün bulunamadı.")

if __name__ == "__main__":
    run()
