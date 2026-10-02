#!/usr/bin/env python3
"""TCG Monitor v2 : sorties et restocks Pokémon & One Piece, alertes Discord avec estimation de revente.

Usage :
  python monitor.py              # un seul passage
  python monitor.py --loop 30    # en continu (mode serveur), un passage toutes les 30 s
Variables d'environnement :
  DISCORD_WEBHOOK_URL            # sans elle : mode test, alertes affichées dans la console
  EBAY_CLIENT_ID / EBAY_CLIENT_SECRET   # optionnel : estimation automatique du prix de revente
"""
import argparse
import base64
import json
import os
import re
import statistics
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state.json"
CONFIG_FILE = ROOT / "config.yaml"
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
FRANCHISES = {
    "pokemon": {"label": "Pokémon", "emoji": "⚡", "color": 0xFFCB05, "cardmarket": "Pokemon"},
    "onepiece": {"label": "One Piece", "emoji": "🏴‍☠️", "color": 0xD62828, "cardmarket": "OnePiece"},
}
PRODUCT_TYPES = [  # ordre important : du plus précis au plus large
    ("ETB", ["elite trainer", "etb", "dresseur d'elite", "dresseur delite"]),
    ("Display / Booster box", ["display", "booster box", "boite de boosters", "boite de 36", "boite de 24"]),
    ("Starter deck", ["starter deck", "deck de demarrage", "deck starter"]),
    ("Coffret", ["coffret", "collection", "premium", "upc", "bundle", "gift"]),
    ("Booster", ["booster", "tripack", "tri-pack", "blister", "double pack"]),
]
GREEN, ORANGE, RED, BLUE = 0x2ECC71, 0xF39C12, 0xE74C3C, 0x3498DB


# ================= Utilitaires =================
def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return text.lower()


def tokens(text):
    return re.findall(r"[a-z0-9\-]+", normalize(text))


def euro(v):
    return f"{v:.2f} €".replace(".", ",") if isinstance(v, (int, float)) else None


def to_float(v, cents=False):
    try:
        f = float(v)
        return f / 100 if cents else f
    except (TypeError, ValueError):
        return None


def base_url(url):
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def fetch(url, **kwargs):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kwargs)
    if r.status_code in (403, 429, 503):
        raise RuntimeError(f"accès bloqué par le site (HTTP {r.status_code})")
    r.raise_for_status()
    return r


def load_config():
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def detect_franchise(title, cfg):
    t = normalize(title)
    for key, words in (cfg.get("franchises") or {}).items():
        if any(normalize(w) in t for w in words or []):
            return key
    return None


def detect_type(title):
    t = normalize(title)
    for label, words in PRODUCT_TYPES:
        if any(w in t for w in words):
            return label
    return None


def is_target(title, cfg):
    """Renvoie la franchise si le produit est un scellé Pokémon/One Piece qui nous intéresse, sinon None."""
    franchise = detect_franchise(title, cfg)
    if not franchise:
        return None
    t = normalize(title)
    if any(normalize(x) in t for x in cfg.get("exclude") or []):
        return None
    return franchise if detect_type(title) else None


# ================= Estimation de revente =================
STOPWORDS = {"de", "du", "des", "la", "le", "les", "et", "en", "a", "au", "aux", "l", "d", "un", "une",
             "jcc", "tcg", "jeu", "cartes", "carte", "collectionner", "fr", "francais", "francaise",
             "version", "vf", "neuf", "scelle", "officiel", "officielle", "the", "card", "game", "of", "-"}
BAD_LISTINGS = ["vide", "empty", "lot de", "proxy", "fake", "sans booster", "carte seule", "custom"]
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def build_query(title):
    return " ".join([t for t in tokens(title) if t not in STOPWORDS][:10])


class Resale:
    def __init__(self, state):
        self.cache = state.setdefault("resale_cache", {})
        self.cid = os.environ.get("EBAY_CLIENT_ID")
        self.secret = os.environ.get("EBAY_CLIENT_SECRET")
        self._token, self._token_exp = None, 0

    def configure(self, cfg):
        r = cfg.get("resale") or {}
        self.fees = float(r.get("fees_pct", 10)) / 100
        self.shipping = float(r.get("shipping_cost", 0))
        self.min_margin = float(r.get("min_margin", 10))
        self.references = r.get("reference_prices") or {}
        self.ttl = float(r.get("cache_hours", 12)) * 3600
        now = time.time()
        for k in [k for k, v in self.cache.items() if now - v.get("t", 0) > self.ttl]:
            del self.cache[k]

    def estimate(self, title, prod_cfg):
        if prod_cfg.get("resale_price"):
            p = float(prod_cfg["resale_price"])
            return {"low": p, "median": p, "n": None, "source": "ton prix de référence"}
        nt = normalize(title)
        for key, price in self.references.items():
            if normalize(key) in nt:
                return {"low": float(price), "median": float(price), "n": None, "source": f"référence « {key} »"}
        if not (self.cid and self.secret):
            return None
        query = prod_cfg.get("resale_query") or build_query(title)
        cached = self.cache.get(query)
        if cached and time.time() - cached["t"] < self.ttl:
            return cached["data"]
        try:
            data = self._ebay(query)
        except Exception as e:
            print(f"[eBay] estimation impossible pour « {query} » : {e}")
            return None
        self.cache[query] = {"t": time.time(), "data": data}
        return data

    def _get_token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        auth = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        r = requests.post(EBAY_TOKEN_URL, timeout=TIMEOUT,
                          headers={"Authorization": f"Basic {auth}",
                                   "Content-Type": "application/x-www-form-urlencoded"},
                          data={"grant_type": "client_credentials",
                                "scope": "https://api.ebay.com/oauth/api_scope"})
        r.raise_for_status()
        j = r.json()
        self._token, self._token_exp = j["access_token"], time.time() + int(j.get("expires_in", 7200))
        return self._token

    def _ebay(self, query):
        r = requests.get(EBAY_SEARCH_URL, timeout=TIMEOUT,
                         headers={"Authorization": f"Bearer {self._get_token()}",
                                  "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR"},
                         params={"q": query, "limit": 50,
                                 "filter": "conditionIds:{1000},buyingOptions:{FIXED_PRICE},itemLocationCountry:FR"})
        r.raise_for_status()
        qtok = set(query.split())
        prices = []
        for item in r.json().get("itemSummaries", []):
            t = normalize(item.get("title", ""))
            if any(b in t for b in BAD_LISTINGS):
                continue
            if qtok and len(qtok & set(tokens(t))) / len(qtok) < 0.6:
                continue
            p = to_float((item.get("price") or {}).get("value"))
            if p:
                prices.append(p)
        if len(prices) < 3:
            return None
        prices.sort()
        return {"low": prices[len(prices) // 4], "median": statistics.median(prices),
                "n": len(prices), "source": "annonces eBay.fr neuves"}

    def margin(self, buy_price, est):
        if buy_price is None or not est:
            return None
        return est["low"] * (1 - self.fees) - self.shipping - buy_price


# ================= Discord =================
def send_discord(webhook, embed):
    payload = {"username": "TCG Monitor", "embeds": [embed]}
    if not webhook:
        print("[TEST - pas de webhook]", json.dumps(payload, ensure_ascii=False)[:1500])
        return
    for _ in range(3):
        try:
            r = requests.post(webhook, json=payload, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 2)))
                continue
            r.raise_for_status()
            return
        except Exception as e:
            print(f"[DISCORD] échec d'envoi : {e}")
            time.sleep(2)


def alert(ctx, kind, info, store_name, prod_cfg=None):
    prod_cfg = prod_cfg or {}
    title, url = info["title"], info["url"]
    franchise = prod_cfg.get("franchise") or info.get("franchise") or detect_franchise(title, ctx.cfg)
    fr = FRANCHISES.get(franchise, {"label": "TCG", "emoji": "🃏", "color": BLUE, "cardmarket": None})
    est = ctx.resale.estimate(title, prod_cfg)
    marg = ctx.resale.margin(info.get("price"), est)

    if kind == "new":
        head, color = "🆕 NOUVEAU PRODUIT", fr["color"]
        status = {True: "🟢 Déjà disponible", False: "⏳ Pas encore en vente (précommande à venir ?)"}.get(
            info.get("in_stock"), "📋 Nouvelle fiche repérée, ouvre-la pour voir le stock")
    else:
        head, color, status = "🟢 EN STOCK", GREEN, "🟢 Disponible maintenant"

    if marg is None:
        verdict = "❔ Rentabilité inconnue"
    elif marg >= ctx.resale.min_margin:
        verdict = "✅ Rentable"
    elif marg > 0:
        verdict, color = "⚠️ Marge faible", ORANGE if kind != "new" else color
    else:
        verdict, color = "❌ Pas rentable", RED if kind != "new" else color

    lines = [f"**{status}** · {verdict}"]
    if info.get("cart_url") and info.get("in_stock"):
        lines.append(f"\n👉 **[AJOUTER AU PANIER]({info['cart_url']})**")
    lines.append(f"🔗 [Fiche produit]({url})")
    q = quote_plus(prod_cfg.get("resale_query") or build_query(title))
    checks = [f"[Ventes eBay conclues](https://www.ebay.fr/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1)"]
    checks.append(f"[Vinted](https://www.vinted.fr/catalog?search_text={q})")
    if fr["cardmarket"]:
        checks.append(f"[Cardmarket](https://www.cardmarket.com/fr/{fr['cardmarket']}/Products/Search?searchString={q})")
    lines.append("🔎 Vérifier la revente : " + " · ".join(checks))

    fields = {
        "Franchise": f"{fr['emoji']} {fr['label']}",
        "Type": detect_type(title) or "—",
        "Boutique": store_name,
        "Prix boutique": euro(info.get("price")) or "—",
    }
    if info.get("variant") and info["variant"] not in ("Default Title", title):
        fields["Variante"] = info["variant"]
    if est:
        n = f" · {est['n']} annonces" if est.get("n") else ""
        fields["Revente estimée"] = f"~{euro(est['low'])} (bas) · {euro(est['median'])} (médian)\n_{est['source']}{n}_"
    else:
        fields["Revente estimée"] = "Pas assez de données"
    if marg is not None:
        pct = f" ({marg / info['price'] * 100:+.0f} %)" if info.get("price") else ""
        fields["Marge nette estimée"] = f"{'+' if marg >= 0 else ''}{euro(marg)}{pct}\n_après {ctx.resale.fees * 100:.0f} % de frais_"

    embed = {
        "title": f"{head} · {title}"[:256],
        "url": url,
        "description": "\n".join(lines)[:4000],
        "color": color,
        "fields": [{"name": k, "value": str(v)[:1024], "inline": True} for k, v in fields.items() if v],
        "footer": {"text": "Estimation indicative basée sur des prix affichés, pas des ventes : vérifie avant d'acheter en volume."},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if info.get("image"):
        embed["thumbnail"] = {"url": info["image"]}
    send_discord(ctx.webhook, embed)
    print(f"[ALERTE] {head} · {title}")


# ================= Lecture des sites =================
def fix_img(src):
    if not src:
        return None
    if isinstance(src, dict):
        src = src.get("url") or src.get("src")
    if isinstance(src, list):
        return fix_img(src[0]) if src else None
    return "https:" + src if str(src).startswith("//") else src


def check_shopify(prod):
    url = prod["url"]
    m = re.search(r"/products/([^/?#]+)", url)
    if not m:
        raise ValueError("URL Shopify invalide (doit contenir /products/...)")
    base = base_url(url)
    data = fetch(f"{base}/products/{m.group(1)}.js").json()
    variants = data.get("variants") or []
    available = [v for v in variants if v.get("available")]
    ref = (available or variants or [{}])[0]
    return {
        "title": data.get("title") or prod.get("name"),
        "url": url,
        "in_stock": bool(available),
        "price": to_float(ref.get("price"), cents=True),
        "variant": ref.get("title"),
        "cart_url": f"{base}/cart/add?id={ref['id']}&quantity=1" if available else None,
        "image": fix_img(data.get("featured_image")),
    }


def _iter_jsonld(obj):
    if isinstance(obj, list):
        for o in obj:
            yield from _iter_jsonld(o)
    elif isinstance(obj, dict):
        yield obj
        for key in ("@graph", "offers", "hasVariant", "itemListElement", "item", "mainEntity"):
            if key in obj:
                yield from _iter_jsonld(obj[key])


def check_generic(prod):
    url = prod["url"]
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    title = prod.get("name") or (soup.title.get_text(strip=True) if soup.title else url)
    image, price, availabilities = None, None, []
    og = soup.find("meta", property="og:image")
    if og:
        image = og.get("content")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except json.JSONDecodeError:
            continue
        for node in _iter_jsonld(data):
            if node.get("@type") == "Product":
                image = image or fix_img(node.get("image"))
            if "availability" in node:
                availabilities.append(str(node["availability"]))
                price = price or to_float(node.get("price") or node.get("lowPrice"))
    in_stock = None
    if availabilities:
        in_stock = any(re.search(r"InStock|PreOrder|LimitedAvailability|OnlineOnly", a) for a in availabilities)
    if prod.get("in_stock_text") or prod.get("out_of_stock_text"):
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = normalize(soup.get_text(" ", strip=True))
        if prod.get("in_stock_text"):
            in_stock = normalize(prod["in_stock_text"]) in text
        else:
            in_stock = normalize(prod["out_of_stock_text"]) not in text
    return {"title": title, "url": url, "in_stock": in_stock, "price": price, "cart_url": None, "image": fix_img(image)}


def check_product(prod):
    return check_shopify(prod) if prod.get("type") == "shopify" else check_generic(prod)


def fetch_store(store):
    base = store["url"].rstrip("/")
    products, page = [], 1
    while page <= 5:
        batch = fetch(f"{base}/products.json", params={"limit": 250, "page": page}).json().get("products", [])
        products += batch
        if len(batch) < 250:
            break
        page += 1
    return products


def expand_pages(cfg):
    """Transforme chaque page de recherche {q} en une URL par terme de recherche."""
    terms = cfg.get("search_terms") or ["pokemon"]
    pages = []
    for site in cfg.get("watch_pages") or []:
        for term in (terms if "{q}" in site["url"] else [None]):
            url = site["url"].replace("{q}", quote_plus(term)) if term else site["url"]
            pages.append({**site, "url": url})
    return pages


def fetch_listing(page):
    """Lit une page de recherche/catégorie et renvoie {url_produit: infos} pour les produits visibles."""
    url = page["url"]
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    domain = urlparse(url).netloc
    items = {}
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except json.JSONDecodeError:
            continue
        for node in _iter_jsonld(data):
            item = node.get("item") if isinstance(node.get("item"), dict) else node
            if item.get("@type") == "Product" and item.get("name") and item.get("url"):
                offers = item.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                avail = str(offers.get("availability", ""))
                items[urljoin(url, item["url"])] = {
                    "title": item["name"], "price": to_float(offers.get("price") or offers.get("lowPrice")),
                    "in_stock": (bool(re.search(r"InStock|PreOrder", avail)) if avail else None),
                    "image": fix_img(item.get("image")),
                }
    pattern = re.compile(page["link_pattern"]) if page.get("link_pattern") else None
    for a in soup.find_all("a", href=True):
        text = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        if len(text) < 10:
            continue
        href = urljoin(url, a["href"]).split("#")[0]
        if urlparse(href).netloc != domain or (pattern and not pattern.search(href)):
            continue
        items.setdefault(href, {"title": text, "price": None, "in_stock": None, "image": None})
    return items


# ================= Traitement =================
class Ctx:
    pass


def handle_product(ctx, prod, future):
    name = prod.get("name") or prod["url"]
    try:
        info = future.result()
    except Exception as e:
        print(f"[ERREUR] {name} : {e}")
        return
    if prod.get("name"):
        info["title"] = prod["name"]
    if info["in_stock"] is None:
        print(f"[?] {name} : stock non détecté, ajoute in_stock_text ou out_of_stock_text dans config.yaml")
        return
    prev = ctx.state["products"].get(prod["url"], {}).get("in_stock")
    if info["in_stock"] and prev is not True:
        alert(ctx, "stock", info, urlparse(prod["url"]).netloc.replace("www.", ""), prod)
    ctx.state["products"][prod["url"]] = {"in_stock": info["in_stock"]}
    print(f"[OK] {name} : {'EN STOCK' if info['in_stock'] else 'rupture'}")


def handle_store(ctx, store, future):
    base = store["url"].rstrip("/")
    name = store.get("name") or urlparse(base).netloc.replace("www.", "")
    try:
        products = future.result()
    except Exception as e:
        print(f"[ERREUR] boutique {name} : {e}")
        return
    seen = ctx.state["stores"].setdefault(base, {})
    first_run = not seen  # 1er passage : on mémorise sans alerter
    count = 0
    for p in products:
        title = p.get("title", "")
        franchise = is_target(title, ctx.cfg)
        if not franchise:
            continue
        count += 1
        pid = str(p["id"])
        variants = p.get("variants") or []
        available = [v for v in variants if v.get("available")]
        ref = (available or variants or [{}])[0]
        images = p.get("images") or []
        info = {
            "title": title, "url": f"{base}/products/{p['handle']}", "franchise": franchise,
            "in_stock": bool(available), "price": to_float(ref.get("price")), "variant": ref.get("title"),
            "cart_url": f"{base}/cart/add?id={ref['id']}&quantity=1" if available else None,
            "image": fix_img(images[0].get("src")) if images else None,
        }
        prev = seen.get(pid)
        if not first_run:
            if prev is None:
                alert(ctx, "new", info, name)
            elif info["in_stock"] and not prev:
                alert(ctx, "stock", info, name)
        seen[pid] = info["in_stock"]
    print(f"[SCAN] {name} : {count} produits suivis{' (initialisation, pas d alerte)' if first_run else ''}")


def handle_page(ctx, page, future):
    name = page.get("name") or urlparse(page["url"]).netloc
    try:
        items = future.result()
    except Exception as e:
        print(f"[ERREUR] page {name} : {e}")
        return
    seen = ctx.state.setdefault("pages", {}).setdefault(page["url"], {})
    first_run = not seen
    count = 0
    for url, it in items.items():
        franchise = is_target(it["title"], ctx.cfg)
        if not franchise:
            continue
        count += 1
        info = {**it, "url": url, "franchise": franchise, "cart_url": None}
        prev = seen.get(url, "absent")
        if not first_run:
            if prev == "absent":
                alert(ctx, "new", info, name)
            elif info["in_stock"] and prev is False:
                alert(ctx, "stock", info, name)
        seen[url] = info["in_stock"]
    if first_run and not seen:
        seen["__init__"] = True  # page vide : on note qu'elle a déjà été lue
    print(f"[PAGE] {name} : {count} produits repérés{' (initialisation)' if first_run else ''}")


def run_once(ctx, pool):
    ctx.cfg = load_config()
    ctx.resale.configure(ctx.cfg)
    products = ctx.cfg.get("products") or []
    stores = ctx.cfg.get("shopify_stores") or []
    prod_futs = [(p, pool.submit(check_product, p)) for p in products]
    store_futs = [(s, pool.submit(fetch_store, s)) for s in stores]
    page_futs = [(pg, pool.submit(fetch_listing, pg)) for pg in expand_pages(ctx.cfg)]
    for p, f in prod_futs:
        handle_product(ctx, p, f)
    for s, f in store_futs:
        handle_store(ctx, s, f)
    for pg, f in page_futs:
        handle_page(ctx, pg, f)
    save_state(ctx.state)


def diagnose(ctx):
    """Teste chaque site configuré et dit ce qui fonctionne depuis cette machine."""
    ctx.cfg = load_config()
    print("\n=== DIAGNOSTIC DES SITES ===\n")
    domains = {}
    for pg in expand_pages(ctx.cfg):
        domains.setdefault(urlparse(pg["url"]).netloc, []).append(pg)
    for domain, pages in domains.items():
        name = pages[0].get("name") or domain
        try:
            r = requests.get(f"https://{domain}/products.json", headers=HEADERS, timeout=TIMEOUT, params={"limit": 1})
            if r.ok and "products" in r.json():
                print(f"🛒 {name} : boutique SHOPIFY → déplace-la dans shopify_stores (ajout au panier en 1 clic)")
                continue
        except Exception:
            pass
        for pg in pages:
            try:
                items = fetch_listing(pg)
                hits = [i["title"] for i in items.values() if is_target(i["title"], ctx.cfg)]
                if hits:
                    print(f"✅ {name} : {len(hits)} produits lus · ex. « {hits[0][:60]} » · {pg['url']}")
                else:
                    print(f"⚠️  {name} : page lue mais 0 produit reconnu (URL de recherche à corriger, ou résultats chargés en JavaScript) · {pg['url']}")
            except Exception as e:
                print(f"❌ {name} : {e} · {pg['url']}")
    for st in ctx.cfg.get("shopify_stores") or []:
        try:
            n = len(fetch_store(st))
            print(f"🛒 {st.get('name') or st['url']} : {n} produits dans le catalogue Shopify")
        except Exception as e:
            print(f"❌ {st.get('name') or st['url']} : {e}")
    print("\nRappel : un site bloqué depuis un serveur peut marcher depuis ta box, et inversement.")


def test_alert(ctx):
    ctx.cfg = load_config()
    ctx.resale.configure(ctx.cfg)
    info = {"title": "Display One Piece OP-09 (ALERTE DE TEST)", "url": "https://example.com", "franchise": "onepiece",
            "in_stock": True, "price": 119.90, "cart_url": "https://example.com", "image": None}
    alert(ctx, "stock", info, "Test", {"resale_price": 180})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, default=0, help="secondes entre deux passages (0 = un seul passage)")
    parser.add_argument("--diagnose", action="store_true", help="teste tous les sites configurés")
    parser.add_argument("--test-alert", action="store_true", help="envoie une fausse alerte sur Discord")
    args = parser.parse_args()
    ctx = Ctx()
    ctx.webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    ctx.state = load_state()
    ctx.state.setdefault("products", {})
    ctx.state.setdefault("stores", {})
    ctx.state.setdefault("pages", {})
    ctx.resale = Resale(ctx.state)
    if args.diagnose:
        return diagnose(ctx)
    if args.test_alert:
        return test_alert(ctx)
    with ThreadPoolExecutor(max_workers=8) as pool:
        if not args.loop:
            run_once(ctx, pool)
            return
        interval = max(args.loop, 30)  # en dessous, les sites risquent de te bloquer
        print(f"Monitoring lancé : un passage toutes les {interval} s")
        while True:
            start = time.time()
            try:
                run_once(ctx, pool)
            except Exception:
                traceback.print_exc()
            time.sleep(max(0, interval - (time.time() - start)))


if __name__ == "__main__":
    main()
