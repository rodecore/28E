#!/usr/bin/env python3
"""
28E RADIO — SERVICIO UNIFICADO DE NOTICIAS EN VIVO (OPCIÓN A + RESPALDO B)

Recolecta titulares recientes desde fuentes RSS/Atom y efemérides reales del día
(Wikimedia + catálogo verificado), selecciona con Gemini Flash cuando está configurado y conserva el texto original
del medio, con caducidad, historial reciente y respaldo RSS automático.
"""

import argparse
import datetime
import html
import hashlib
import fcntl
from contextlib import contextmanager
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime

# Zona horaria oficial de la audiencia base (Caracas y Santo Domingo: UTC-4)
LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=-4))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
HTTP_UA = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)
WIKIMEDIA_UA = '28E-Radio-News/2.0 (https://28e.live)'

VALID_CATEGORIES = [
    'INTERNACIONAL',
    'VENEZUELA',
    'REP. DOMINICANA',
    'ECONOMÍA',
    'TECNOLOGÍA',
    'CULTURA & MÚSICA',
    'GAMING',
    'DEPORTES',
]
EFEMERIDE_CATEGORY = 'UN DÍA COMO HOY'

# Límites de antigüedad estrictos (en horas) para garantizar noticias actuales
MAX_AGE_BY_CATEGORY = {
    'INTERNACIONAL': 28,
    'VENEZUELA': 32,
    'REP. DOMINICANA': 32,
    'ECONOMÍA': 36,
    'DEPORTES': 30,
    'TECNOLOGÍA': 42,
    'CULTURA & MÚSICA': 48,
    'GAMING': 48,
}

# Cada entrada: (categoría_origen, nombre_medio, url_rss, max_age_horas, idioma)
FEEDS = [
    # Internacional (español neutro, tono de agencia)
    ('INTERNACIONAL', 'BBC Mundo', 'https://feeds.bbci.co.uk/mundo/rss.xml', 28, 'es'),
    ('INTERNACIONAL', 'DW Español', 'https://rss.dw.com/xml/rss-sp-all', 28, 'es'),
    ('INTERNACIONAL', 'France 24', 'https://www.france24.com/es/rss', 28, 'es'),
    ('INTERNACIONAL', 'El País América', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/america/portada', 28, 'es'),
    ('INTERNACIONAL', 'El País Internacional', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada', 28, 'es'),

    # Venezuela
    ('VENEZUELA', 'TalCual', 'https://talcualdigital.com/feed/', 32, 'es'),
    ('VENEZUELA', 'Runrunes', 'https://runrun.es/feed/', 32, 'es'),
    ('VENEZUELA', 'El Diario', 'https://eldiario.com/feed/', 32, 'es'),

    # República Dominicana
    ('REP. DOMINICANA', 'Diario Libre', 'https://www.diariolibre.com/rss/actualidad.xml', 32, 'es'),
    ('REP. DOMINICANA', 'El Nacional', 'https://elnacional.com.do/feed/', 32, 'es'),
    ('REP. DOMINICANA', 'El Día', 'https://eldia.com.do/feed/', 32, 'es'),

    # Economía
    ('ECONOMÍA', 'El País Economía', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada', 36, 'es'),
    ('ECONOMÍA', 'Diario Libre Economía', 'https://www.diariolibre.com/rss/economia.xml', 36, 'es'),
    ('ECONOMÍA', 'DW Economía', 'https://rss.dw.com/xml/rss-sp-eco', 36, 'es'),
    ('ECONOMÍA', 'France 24 Economía', 'https://www.france24.com/es/econom%C3%ADa/rss', 36, 'es'),

    # Tecnología & Ciencia
    ('TECNOLOGÍA', 'Xataka', 'https://feeds.weblogssl.com/xataka2', 42, 'es'),
    ('TECNOLOGÍA', 'Genbeta', 'https://feeds.weblogssl.com/genbeta', 42, 'es'),
    ('TECNOLOGÍA', 'Hipertextual', 'https://hipertextual.com/feed', 42, 'es'),
    ('TECNOLOGÍA', 'Wired en Español', 'https://es.wired.com/feed/rss', 42, 'es'),
    ('TECNOLOGÍA', 'El País Tecnología', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada', 42, 'es'),

    # Cultura y música
    ('CULTURA & MÚSICA', 'El País Cultura', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/cultura/portada', 48, 'es'),
    ('CULTURA & MÚSICA', 'Jenesaispop', 'https://jenesaispop.com/feed/', 48, 'es'),
    ('GAMING', 'Eurogamer.es', 'https://www.eurogamer.es/feed/news', 48, 'es'),
    ('GAMING', 'Gamereactor.es', 'https://www.gamereactor.es/rss/rss.php?texttype=4', 48, 'es'),

    # Deportes
    ('DEPORTES', 'El País Deportes', 'https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/deportes/portada', 30, 'es'),
    ('DEPORTES', 'France 24 Deportes', 'https://www.france24.com/es/deportes/rss', 30, 'es'),
    ('DEPORTES', 'Diario Libre Deportes', 'https://www.diariolibre.com/rss/deportes.xml', 30, 'es'),
    ('DEPORTES', 'Marca', 'https://e00-marca.uecdn.es/rss/portada.xml', 28, 'es'),
]

# Efemérides verificadas adicionales (solo se muestran si mes y día coinciden con hoy en UTC-4)
EXACT_DATE_EFEMERIDES = [
    (11, 15, 1971, 'En 1971, Intel presentó el Intel 4004, primer microprocesador comercial en un único chip'),
    (11, 15, 2001, 'En 2001, Microsoft lanzó la primera consola Xbox junto a Halo: Combat Evolved'),
    (11, 16, 2004, 'En 2004, Valve lanzó Half-Life 2 para PC e impulsó la plataforma digital Steam'),
    (11, 17, 2006, 'En 2006, Sony lanzó la consola PlayStation 3 en el mercado norteamericano'),
    (11, 18, 1928, 'En 1928, Disney estrenó Steamboat Willie, primer corto animado sonoro de Mickey Mouse'),
    (11, 19, 1998, 'En 1998, Valve publicó el primer Half-Life en PC y transformó la acción en primera persona'),
    (11, 20, 1985, 'En 1985, Microsoft lanzó la primera versión de Windows 1.0 como entorno gráfico'),
    (11, 21, 1990, 'En 1990, Nintendo lanzó la consola Super Famicom en Japón junto a Super Mario World'),
    (11, 21, 1998, 'En 1998, Nintendo lanzó The Legend of Zelda: Ocarina of Time para Nintendo 64'),
    (11, 22, 2005, 'En 2005, Microsoft lanzó la consola Xbox 360, dando inicio a la generación en alta definición'),
    (11, 23, 2004, 'En 2004, Blizzard Entertainment estrenó World of Warcraft en Norteamérica'),
    (11, 27, 1998, 'En 1998, Sega lanzó la consola Dreamcast en Japón con módem integrado de fábrica'),
    (11, 29, 1972, 'En 1972, Atari lanzó Pong en recreativas e inició la industria comercial del videojuego'),
]

HARD_REJECT_PATTERNS = [
    # Preguntas, exclamaciones o citas sensacionalistas / truncadas
    r'[?¿¡!«»“”]',
    r'^["\']',
    # Primera/segunda persona, blogs y clickbait
    r'\b(me fui|he probado|hemos probado|he usado|mi experiencia|analizamos|probamos|te contamos|te explicamos|tu jefe|tu m[oó]vil|tu cuenta|puedes|deber[ií]as|olv[ií]date|prep[aá]rate|descubre|conoce|aprende|as[ií] puedes|todo sobre)\b',
    r'^(c[oó]mo|por qu[eé]|cu[aá]ndo|d[oó]nde|qui[eé]n(es)?|qu[eé]\b|cu[aá]l(es)?|lo que|as[ií] (es|se|fue|funciona)|estos son|las \d+|los \d+|\d+\s+(claves|consejos|razones|cosas|formas|trucos|pasos))\b',
    # Opinión, análisis subjetivo, transmisiones en vivo y coberturas minuto a minuto
    r'^(opini[oó]n|tribuna|editorial|columna|an[aá]lisis|review|podcast|en vivo|en directo|minuto a minuto|al minuto|en video|en v[ií]deo|edici[oó]n impresa)\b',
    r'\b(an[aá]lisis|review|cr[ií]tica|opini[oó]n|editorial|columna|primer contacto|impresiones|hor[oó]scopo|edici[oó]n impresa|podcast)\b',
    r'\b(en directo|en vivo|minuto a minuto|al minuto|sigue el partido|sigue la carrera|retransmisi[oó]n)\b',
    # Política doméstica, municipal o transporte local de España (irrelevante para audiencia internacional/hispana)
    r'\b(huelga de maquinistas|huelga de renfe|renfe|adif|cercan[ií]as|dgt|itv|hacienda espa[ñn]ola|smi en espa[ñn]a|ayuntamiento|comunidad aut[oó]noma|pe[ñn]istas|diputaci[oó]n|expediente\w* sancionador\w*|multas? de tr[aá]fico)\b',
    # Vago o clickbait sensacionalista
    r'\b(marca otro hito hist[oó]rico|hace historia|rompe el silencio|revela la verdad|no te lo vas a creer)\b',
    # Ofertas comerciales, liquidaciones y SEO de trámites
    r'\b(descuento\w*|black friday|black november|oferta\w*|rebaja\w*|rebajad\w*|ganga|choll\w*|cazando gangas|liquida\w*|mejor precio|en oferta|a precio m[ií]nimo|por \d+\s*(euros?|d[oó]lares?)|ahorra\w*|por menos de|gratis|sorteo|cup[oó]n)\b',
    r'\b(cronograma|surtir gasolina|precio del pasaporte|bono de la patria|sistema patria|carnet de la patria|requisitos para|paso a paso|d[oó]nde consultar)\b',
    # Crónica roja morbosa y farándula/virales
    r'\b(descuartiz\w*|hallan cad[aá]ver\w*|cad[aá]ver\w*|sicarios|acribillan|matan a balazos|violador\w*|femicid\w*|feminicid\w*|pornograf\w*)\b',
    r'\b(tiktoker|influencer|furor en redes|se vuelve viral|se viraliza|outfit|bikini|alfombra roja|luce irreconocible)\b',
    # Dos oraciones seguidas con remate
    r'\.\s+[A-ZÁÉÍÓÚÑ¿¡]',
]
HARD_REJECT_RE = re.compile('|'.join(HARD_REJECT_PATTERNS), re.IGNORECASE)

FOREIGN_COUNTRY_RE = re.compile(
    r'\b(ee\.?\s*uu|estados unidos|panam[aá]|ecuador|m[eé]xico|colombia|ucrania|rusia|israel|gaza|ir[aá]n|espa[ñn]a|francia|alemania|china|argentina|brasil|chile|per[uú])\b',
    re.IGNORECASE,
)

BAD_URL_RE = re.compile(
    r'/(opinion|tribuna|editorial|editoriales|columnistas|blogs|podcast|horoscopo|horoscopos|escaparate|compras|ofertas|descuentos|gente|famosos)/',
    re.IGNORECASE
)
BAD_RSS_CAT_TOKENS = ('opinión', 'opinion', 'editorial', 'tribuna', 'columna', 'horóscopo', 'horoscopo', 'ofertas', 'escaparate', 'blog')

TOPIC_STOPWORDS = {
    'para', 'como', 'este', 'esta', 'estos', 'estas', 'pero', 'mas', 'más', 'sobre',
    'entre', 'hasta', 'desde', 'tras', 'ante', 'bajo', 'contra', 'segun', 'según',
    'nuevo', 'nueva', 'nuevos', 'nuevas', 'primer', 'primera', 'puede', 'pueden',
    'podria', 'podría', 'sera', 'será', 'años', 'anos', 'millones', 'mundo',
    'lanza', 'presenta', 'anuncia', 'confirma', 'asegura', 'supera', 'llega',
    'gobierno', 'nacional', 'venezuela', 'dominicana', 'republica', 'república',
}


def load_dotenv(paths=None):
    """Carga variables desde .env sin sobrescribir las ya presentes en os.environ."""
    if paths is None:
        paths = [
            os.path.join(REPO_ROOT, '.env'),
            os.path.join(SCRIPT_DIR, '.env'),
            '/opt/radio28e/news.env',
        ]
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ and val:
                        os.environ[key] = val
        except OSError:
            pass


def strip_html(raw):
    if not raw:
        return ''
    txt = re.sub(r'<!\[CDATA\[([\s\S]*?)\]\]>', r'\1', raw)
    txt = html.unescape(txt)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = re.sub(r'https?://\S+', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt


def clean_title(raw_title, source_name=''):
    t = strip_html(raw_title)
    if not t:
        return ''
    t = re.sub(
        r'^(FOTOS|VIDEO|VÍDEO|EN IMÁGENES|EN FOTOS|TRÁILER|TRAILER|INFORME|OFICIAL|NOTICIA|ÚLTIMA HORA|EN VIVO|EN DIRECTO|DIRECTO|MINUTO A MINUTO|AL MINUTO|RESUMEN|#EnClaves|EN CLAVES?|URGENTE|PRIMICIA)\s*[:|—–-]\s*',
        '',
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r'[,|\-—–]?\s*\b(en directo|en vivo|al minuto|minuto a minuto)\s*$', '', t, flags=re.IGNORECASE)
    if source_name:
        escaped = re.escape(source_name)
        t = re.sub(rf'\s+[-|—–]\s+{escaped}$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+[-|—–]\s+(BBC News Mundo|DW|El País|Diario Libre|Xataka|Genbeta|Hipertextual|ESPN|Marca)$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\.{2,}$', '', t)
    t = re.sub(r'\.+$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def clean_summary(raw_desc, max_chars=260):
    s = strip_html(raw_desc)
    if not s:
        return ''
    s = re.sub(r'(Lee más|Leer más|Seguir leyendo|La entrada .+ se publicó primero en .+)$', '', s, flags=re.IGNORECASE).strip()
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars].rsplit(' ', 1)[0]
    return cut + '…'


def parse_entry_datetime(text):
    """Convierte fecha RFC-2822 o ISO-8601 a datetime aware en UTC."""
    if not text:
        return None
    val = text.strip()
    try:
        dt = parsedate_to_datetime(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        pass

    iso = val[:-1] + '+00:00' if val.endswith('Z') else val
    iso = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', iso)
    try:
        dt = datetime.datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def local_name(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def first_child_text(node, names):
    for child in node:
        if local_name(child.tag) in names and child.text and child.text.strip():
            return child.text
    return ''


def collect_entry_links(node):
    links = []
    for child in node:
        name = local_name(child.tag)
        if name == 'link':
            href = child.attrib.get('href') or child.text or ''
            if href.strip():
                links.append(href.strip())
    return links[0] if links else ''


def collect_entry_categories(node):
    cats = []
    for child in node:
        if local_name(child.tag) == 'category':
            val = child.attrib.get('term') or child.text or ''
            if val.strip():
                cats.append(val.strip())
    return cats


GAMING_HEADLINE_RE = re.compile(r'\b(videojuegos?|gameplay|dlc|firefight|playstation|xbox|nintendo|steam|fortnite|minecraft|pubg|half-life|halo:\s*campaign|halo\s+campaign|the outer worlds)\b', re.IGNORECASE)
GAMING_SOURCES = {'Eurogamer.es', 'Gamereactor.es'}


def classify_news_category(category, title, source=''):
    if GAMING_HEADLINE_RE.search(title) or source in GAMING_SOURCES:
        return 'GAMING'
    return category


def news_state_dir():
    return os.environ.get('NEWS_STATE_DIR', os.path.join(REPO_ROOT, '.cache', 'radio-news'))


def load_news_history(now_utc):
    try:
        with open(os.path.join(news_state_dir(), 'history.json'), encoding='utf-8') as handle:
            history = json.load(handle)
        cutoff = now_utc.timestamp() - 6 * 3600
        return {key: value for key, value in history.items()
                if isinstance(value, (int, float)) and value > cutoff}
    except (OSError, ValueError, AttributeError):
        return {}


def save_news_state(filename, data):
    os.makedirs(news_state_dir(), exist_ok=True)
    target = os.path.join(news_state_dir(), filename)
    temporary = target + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, target)


@contextmanager
def news_update_lock():
    os.makedirs(news_state_dir(), exist_ok=True)
    with open(os.path.join(news_state_dir(), 'update.lock'), 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def article_id(item):
    # El título original identifica también republicaciones con otra URL.
    text = re.sub(r'[^a-záéíóúñü0-9]', '', item['title'].lower())
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]


def news_metadata(candidate):
    published = parse_entry_datetime(candidate['publishedAt'])
    expiry = published + datetime.timedelta(hours=MAX_AGE_BY_CATEGORY[candidate['origin']])
    return {
        'id': article_id(candidate),
        'url': candidate.get('link', ''),
        'publishedAt': candidate['publishedAt'],
        'expiresAt': expiry.strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def efemeride_expiry(today_local=None):
    today_local = today_local or datetime.datetime.now(LOCAL_TZ).date()
    midnight = datetime.datetime.combine(today_local + datetime.timedelta(days=1),
                                         datetime.time(), LOCAL_TZ)
    return midnight.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fetch_single_feed(feed_spec, now_utc, health=None):
    origin_cat, source_name, url, max_age_hours, lang = feed_spec
    items = []
    started = time.monotonic()
    raw_xml = None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': HTTP_UA})
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            raw_xml = resp.read()
    except urllib.error.HTTPError as he:
        # Fallback con curl si el servidor bloquea el TLS/fingerprint de urllib (ej. Cloudflare en El Diario)
        if he.code in (403, 429):
            try:
                res = subprocess.run(
                    ['curl', '-s', '-m', '10', '-A', HTTP_UA, url],
                    capture_output=True,
                    timeout=12,
                )
                if res.returncode == 0 and (b'<rss' in res.stdout or b'<feed' in res.stdout or b'<?xml' in res.stdout):
                    raw_xml = res.stdout
            except Exception:
                pass
        if raw_xml is None:
            if health is not None:
                health[source_name] = {'ok': False, 'url': url, 'error': str(he),
                                       'accepted': 0, 'elapsedSeconds': round(time.monotonic() - started, 2)}
            print(f'[NEWS_SERVICE] Error en feed {source_name} ({url}): {he}', file=sys.stderr, flush=True)
            return items
    except Exception as e:
        if health is not None:
            health[source_name] = {'ok': False, 'url': url, 'error': str(e),
                                   'accepted': 0, 'elapsedSeconds': round(time.monotonic() - started, 2)}
        print(f'[NEWS_SERVICE] Error en feed {source_name} ({url}): {e}', file=sys.stderr, flush=True)
        return items

    try:
        root = ET.fromstring(raw_xml)
    except Exception as e:
        if health is not None:
            health[source_name] = {'ok': False, 'url': url, 'error': f'XML parse: {e}',
                                   'accepted': 0, 'elapsedSeconds': round(time.monotonic() - started, 2)}
        print(f'[NEWS_SERVICE] Error parseando XML de {source_name}: {e}', file=sys.stderr, flush=True)
        return items

    entries = [el for el in root.iter() if local_name(el.tag) in ('item', 'entry')]
    for entry in entries[:35]:
        raw_title = first_child_text(entry, ('title',))
        title = clean_title(raw_title, source_name)
        if not title or len(title) < 20:
            continue

        date_str = first_child_text(entry, ('pubDate', 'date', 'published', 'updated'))
        pub_dt = parse_entry_datetime(date_str)
        if pub_dt is None:
            continue  # Cero noticias sin fecha verificable

        age_hours = (now_utc - pub_dt).total_seconds() / 3600.0
        if age_hours < -2.0 or age_hours > max_age_hours:
            continue

        link = collect_entry_links(entry)
        if link and BAD_URL_RE.search(link):
            continue

        cats = collect_entry_categories(entry)
        if any(any(tok in c.lower() for tok in BAD_RSS_CAT_TOKENS) for c in cats):
            continue

        if HARD_REJECT_RE.search(title):
            continue

        raw_desc = first_child_text(entry, ('description', 'summary', 'encoded', 'content'))
        summary = clean_summary(raw_desc)
        if summary and re.search(r'\b(hor[oó]scopo|tarot|descuento exclusivo|c[oó]digo promocional)\b', summary, re.IGNORECASE):
            continue

        items.append({
            'origin': classify_news_category(origin_cat, title, source_name),
            'source': source_name,
            'lang': lang,
            'title': title,
            'summary': summary,
            'link': link,
            'pub_dt': pub_dt,
            'publishedAt': pub_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'age_hours': round(age_hours, 1),
        })

    if health is not None:
        health[source_name] = {'ok': True, 'url': url, 'entries': len(entries),
                               'accepted': len(items), 'elapsedSeconds': round(time.monotonic() - started, 2)}
    items.sort(key=lambda x: x['age_hours'])
    return items


def extract_topic_tokens(title):
    words = re.findall(r'[a-záéíóúñü0-9]{4,}', title.lower())
    return {w for w in words if w not in TOPIC_STOPWORDS}


def is_similar_topic(tokens, existing_sets):
    if not tokens:
        return False
    for prev in existing_sets:
        overlap = len(tokens & prev)
        min_len = min(len(tokens), len(prev))
        if overlap >= 4 or (min_len >= 3 and overlap / min_len >= 0.65):
            return True
    return False


def collect_candidates(now_utc, history=None, health=None):
    all_raw = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_single_feed, spec, now_utc, health) for spec in FEEDS]
        for fut in as_completed(futures):
            all_raw.extend(fut.result())

    # Ordenar por frescura y agrupar equilibradamente para que ninguna categoría monopolice el lote
    all_raw.sort(key=lambda x: (article_id(x) in (history or {}), x['age_hours']))
    by_origin = {cat: [] for cat in VALID_CATEGORIES}
    seen_titles = set()
    seen_topics = []

    for it in all_raw:
        it['_seen_recently'] = article_id(it) in (history or {})
        key = re.sub(r'[^a-z0-9áéíóúñ]', '', it['title'].lower())
        if not key or key in seen_titles:
            continue
        tokens = extract_topic_tokens(it['title'])
        if is_similar_topic(tokens, seen_topics):
            continue
        seen_titles.add(key)
        seen_topics.append(tokens)
        by_origin.setdefault(it['origin'], []).append(it)

    # Tomar hasta 12 candidatos frescos por categoría rotando entre medios (máximo 4 por medio)
    balanced = []
    for cat in VALID_CATEGORIES:
        by_src = {}
        for item in by_origin.get(cat, []):
            by_src.setdefault(item['source'], []).append(item)
        picked = []
        for round_idx in range(4):
            for bucket in by_src.values():
                if round_idx < len(bucket) and len(picked) < 12:
                    picked.append(bucket[round_idx])
        balanced.extend(picked)

    for idx, item in enumerate(balanced, start=1):
        item['id'] = idx
    return balanced


def fetch_efemerides_candidates(today_local):
    """Obtiene efemérides reales y verificadas para (mes, día) actual en UTC-4."""
    mm = f'{today_local.month:02d}'
    dd = f'{today_local.day:02d}'
    candidates = []

    for m, d, year, txt in EXACT_DATE_EFEMERIDES:
        if m == today_local.month and d == today_local.day:
            candidates.append({
                'eid': f'E{len(candidates) + 1}',
                'year': year,
                'text': re.sub(r'\.+$', '', txt.strip()),
            })

    for endpoint in ('selected', 'events'):
        if len(candidates) >= 10:
            break
        url = f'https://es.wikipedia.org/api/rest_v1/feed/onthisday/{endpoint}/{mm}/{dd}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': WIKIMEDIA_UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=8, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            rows = data.get(endpoint, [])
            for row in rows:
                year = row.get('year')
                text = strip_html(row.get('text') or '')
                text = re.sub(r'\s*\((?:en la imagen|imagen|fotograf[ií]a)[^)]*\)', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                if not year or not text or len(text) < 20:
                    continue
                if re.search(r'\b(masacre|genocidio|fusilad|asesin|fallec|mueren|m[aá]rtir\w*|violaci[oó]n|terremoto deja \d+ muertos|bombardeo)\b', text, re.IGNORECASE):
                    continue
                if any(c['year'] == year and c['text'][:24].lower() == text[:24].lower() for c in candidates):
                    continue
                candidates.append({
                    'eid': f'E{len(candidates) + 1}',
                    'year': int(year),
                    'text': text,
                })
                if len(candidates) >= 12:
                    break
        except Exception as e:
            print(f'[NEWS_SERVICE] Aviso Wikimedia onthisday ({endpoint}): {e}', file=sys.stderr, flush=True)

    return candidates


def build_gemini_payload(candidates, efemerides, today_local, model=''):
    news_lines = []
    for c in candidates:
        summary_part = f" | Resumen: {c['summary']}" if c['summary'] else ''
        news_lines.append(
            f"[{c['id']}] ({c['origin']} | {c['source']} | hace {c['age_hours']}h) {c['title']}{summary_part}"
        )

    efem_lines = [f"[{e['eid']}] (Año {e['year']}) {e['text']}" for e in efemerides]

    prompt = (
        f"Fecha actual de emisión (Caracas / Santo Domingo UTC-4): {today_local.strftime('%Y-%m-%d')}.\n\n"
        "Eres el editor jefe de noticias de Radio 28E (cintillo de una línea en pantalla 1080p).\n"
        "Tu audiencia principal está en Venezuela, República Dominicana y la comunidad hispana internacional.\n\n"
        "TAREA 1 — SELECCIÓN Y REDACCIÓN DE NOTICIAS:\n"
        "Selecciona entre 20 y 24 noticias REALES de la lista de candidatos.\n"
        "DISTRIBUCIÓN OBLIGATORIA: Elige exactamente 2 a 3 noticias para CADA UNA de las 8 categorías:\n"
        "INTERNACIONAL, VENEZUELA, REP. DOMINICANA, ECONOMÍA, TECNOLOGÍA, CULTURA & MÚSICA, GAMING, DEPORTES.\n\n"
        "CRITERIOS EDITORIALES Y REDACCIÓN ESTILO CABLE 28E:\n"
        "- Redacta para cada noticia un titular conciso, informativo y directo, entre 50 y 90 caracteres (NUNCA menos de 45 ni más de 94 caracteres).\n"
        "- Ortografía y acentuación impecables en español: mantén siempre las tildes, acentos y la letra 'ñ'.\n"
        "- Oración completa autosuficiente: Sujeto concreto + verbo de acción + dato informativo cerrado.\n"
        "- Si la noticia trata de un videojuego, tecnología, artista o empresa, nómbralo claramente por su nombre propio.\n"
        "- PROHIBIDO prefijos o sufijos como 'En directo:', 'En vivo:', 'Minuto a minuto'.\n"
        "- PROHIBIDO signos de exclamación ¡!, interrogación ¿?, comillas dobles o simples, y punto final.\n"
        "- PROHIBIDO inventar hechos, nombres o cifras que no figuren en el candidato.\n"
        "- Si una nota económica o política proviene de Europa o España, nombra explícitamente el país (ej. 'El Gobierno español...' o 'La Unión Europea...') para no generar ambigüedad con Latinoamérica, o prioriza economía internacional.\n"
        "- En TECNOLOGÍA: Selecciona exclusivamente software, hardware, computación, inteligencia artificial, ciencia o ciberseguridad. DESCARTA ofertas y liquidaciones de tiendas (Carrefour, Amazon, etc.) y noticias de multas o ayuntamientos locales.\n"
        "- DESCARTA política doméstica interna, disputas partidistas o huelgas de transporte locales de España (ej. Renfe, maquinistas, debates parlamentarios locales).\n"
        "- DESCARTA notas vecinales o barriales menores de Venezuela o RD (reparaciones de baches, quejas vecinales aisladas).\n"
        "- DESCARTA crónica roja morbosa, notas de opinión subjetivas y rumores de farándula.\n\n"
        "TAREA 2 — EFEMÉRIDES HISTÓRICAS:\n"
        "De la lista de EFEMÉRIDES VERIFICADAS de hoy, elige 1 ó 2 hitos universales destacados (ciencia, música, cultura o tecnología).\n"
        "Conserva el texto verificado iniciando con 'En {año}, ' sin inventar datos.\n\n"
        "CANDIDATOS DE NOTICIAS:\n" + "\n".join(news_lines) + "\n\n"
        "EFEMÉRIDES VERIFICADAS DE HOY:\n" + ("\n".join(efem_lines) if efem_lines else "(Sin efemérides disponibles)")
    )

    schema = {
        'type': 'OBJECT',
        'properties': {
            'news': {
                'type': 'ARRAY',
                'items': {
                    'type': 'OBJECT',
                    'properties': {
                        'source_id': {'type': 'INTEGER'},
                        'category': {'type': 'STRING', 'enum': VALID_CATEGORIES},
                        'title': {'type': 'STRING'},
                    },
                    'required': ['source_id', 'category', 'title'],
                },
                'minItems': 20,
                'maxItems': 24,
            },
            'efemerides': {
                'type': 'ARRAY',
                'items': {
                    'type': 'OBJECT',
                    'properties': {
                        'source_id': {'type': 'STRING'},
                        'title': {'type': 'STRING'},
                    },
                    'required': ['source_id', 'title'],
                },
                'minItems': 1,
                'maxItems': 2,
            },
        },
        'required': ['news', 'efemerides'],
    }

    gen_cfg = {
        'temperature': 0.2,
        'responseMimeType': 'application/json',
        'responseSchema': schema,
    }
    if model and '2.5' not in model:
        gen_cfg['thinkingConfig'] = {'thinkingLevel': 'low'}

    return {
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': gen_cfg,
    }


def sanitize_final_headline(text):
    if not text:
        return ''
    t = strip_html(text)
    t = t.strip(' "\'“”«»')
    t = re.sub(
        r'^(FOTOS|VIDEO|VÍDEO|EN IMÁGENES|EN FOTOS|TRÁILER|TRAILER|INFORME|OFICIAL|NOTICIA|ÚLTIMA HORA|EN VIVO|EN DIRECTO|DIRECTO|MINUTO A MINUTO|AL MINUTO|RESUMEN)\s*[:|—–-]\s*',
        '',
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r'[,|\-—–]?\s*\b(en directo|en vivo|al minuto|minuto a minuto)\s*$', '', t, flags=re.IGNORECASE)
    t = t.replace('"', '').replace('“', '').replace('”', '').replace('«', '').replace('»', '')
    t = re.sub(r'\.+$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _gemini_endpoints():
    preferred = os.environ.get('GEMINI_MODEL', '').strip()
    provider_mode = os.environ.get('GEMINI_API_PROVIDER', 'auto').strip().lower()

    aistudio = (
        'AI Studio',
        'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        list(dict.fromkeys(m for m in [preferred, 'gemini-flash-lite-latest', 'gemini-3.5-flash-lite', 'gemini-flash-latest'] if m)),
    )
    vertex = (
        'Vertex Express',
        'https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent',
        list(dict.fromkeys(m for m in [preferred, 'gemini-2.5-flash', 'gemini-2.5-flash-lite'] if m)),
    )

    if provider_mode == 'aistudio':
        return [aistudio]
    if provider_mode == 'vertex':
        return [vertex]
    return [aistudio, vertex]


def call_gemini_curate(candidates, efemerides, today_local):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        return None, 'GEMINI_API_KEY no configurada'

    last_err = 'sin respuesta'

    for provider_name, url_tpl, models in _gemini_endpoints():
        for model in models:
            payload_bytes = json.dumps(build_gemini_payload(candidates, efemerides, today_local, model=model), ensure_ascii=False).encode('utf-8')
            url = url_tpl.format(model=model)
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                method='POST',
                headers={
                    'Content-Type': 'application/json',
                    'x-goog-api-key': api_key,
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
                    body = json.loads(resp.read().decode('utf-8'))
                text_out = body['candidates'][0]['content']['parts'][0]['text']
                parsed = json.loads(text_out)
                print(f'[NEWS_SERVICE] Mesa editorial Gemini ({provider_name} / {model}) respondió correctamente.', flush=True)
                return parsed, None
            except urllib.error.HTTPError as e:
                err_body = ''
                try:
                    err_body = e.read().decode('utf-8', errors='replace')[:240]
                except Exception:
                    pass
                last_err = f'HTTP {e.code} en {provider_name}/{model}: {err_body}'
                if e.code in (404, 429, 500, 503):
                    continue
                if e.code in (401, 403):
                    break  # La clave no corresponde a este proveedor
                if e.code == 400:
                    if 'API key' in err_body or 'permission' in err_body.lower():
                        break
                    continue
                return None, last_err
            except Exception as e:
                last_err = f'Error en {provider_name}/{model}: {e}'
                continue

    return None, last_err


def validate_gemini_items(parsed, candidates, efemerides):
    by_id = {c['id']: c for c in candidates}
    efem_by_id = {e['eid']: e for e in efemerides}

    curated_news = []
    used_ids = set()

    news_rows = parsed.get('news')
    for row in news_rows if isinstance(news_rows, list) else []:
        if not isinstance(row, dict):
            continue
        sid = row.get('source_id')
        cat = row.get('category')

        if not isinstance(sid, int) or isinstance(sid, bool) or sid not in by_id or sid in used_ids:
            continue
        if cat not in VALID_CATEGORIES:
            continue

        src = dict(by_id[sid])
        gemini_title = sanitize_final_headline(row.get('title', ''))
        src_title = sanitize_final_headline(src['title'])

        chosen_title = None
        # Priorizar el titular refinado por Gemini si cumple las pautas de estilo
        if (
            gemini_title
            and 45 <= len(gemini_title) <= 94
            and not re.search(r'[?¿¡!]', gemini_title)
            and not HARD_REJECT_RE.search(gemini_title)
        ):
            chosen_title = gemini_title
        elif (
            src_title
            and 45 <= len(src_title) <= 94
            and not re.search(r'[?¿¡!]', src_title)
            and not HARD_REJECT_RE.search(src_title)
        ):
            chosen_title = src_title
        elif gemini_title and len(gemini_title) > 94:
            cut = gemini_title[:91].rsplit(' ', 1)[0]
            if len(cut) >= 45 and not HARD_REJECT_RE.search(cut):
                chosen_title = cut

        if not chosen_title:
            continue

        final_category = classify_news_category(cat, chosen_title, src['source'])

        used_ids.add(sid)
        curated_news.append({
            'category': final_category,
            'title': chosen_title,
            'source': src['source'],
            **news_metadata(src),
            '_age_hours': src['age_hours'],
            '_seen_recently': src.get('_seen_recently', False),
        })

    curated_efems = []
    used_eids = set()
    efem_rows = parsed.get('efemerides')
    for row in efem_rows if isinstance(efem_rows, list) else []:
        if not isinstance(row, dict):
            continue
        eid = row.get('source_id')
        if not isinstance(eid, str) or eid not in efem_by_id or eid in used_eids:
            continue
        title = sanitize_final_headline(efem_by_id[eid]['text'])
        year_str = str(efem_by_id[eid]['year'])
        if year_str not in title:
            continue
        if len(title) > 94:
            head = title[:94]
            cut = head.rsplit(',', 1)[0] if ',' in head else head.rsplit(' ', 1)[0]
            if len(cut) >= 45:
                title = cut.rstrip(' ,;:')
            else:
                continue
        if len(title) < 32 or len(title) > 94 or re.search(r'[?¿¡!]', title):
            continue
        used_eids.add(eid)
        curated_efems.append({
            'category': EFEMERIDE_CATEGORY,
            'title': title,
            'source': 'Wikimedia / Archivo 28E',
            'expiresAt': efemeride_expiry(),
        })
        if len(curated_efems) >= 2:
            break

    return curated_news, curated_efems


def build_fallback_items(candidates, efemerides):
    """Respaldo determinístico (Opción B) cuando no hay API key o falla Gemini."""
    news_items = []
    for c in candidates:
        c = dict(c)
        c['origin'] = classify_news_category(c['origin'], c['title'], c['source'])
        if c.get('lang') != 'es':
            continue
        title = sanitize_final_headline(c['title'])
        if len(title) > 94:
            cut = title[:91].rsplit(' ', 1)[0]
            if len(cut) >= 45 and not HARD_REJECT_RE.search(cut):
                title = cut
        if len(title) < 45 or len(title) > 94 or len(title.split()) < 5:
            continue
        if re.search(r'[?¿¡!]', title) or HARD_REJECT_RE.search(title):
            continue
        category = c['origin']
        if category in ('VENEZUELA', 'REP. DOMINICANA') and FOREIGN_COUNTRY_RE.search(title):
            if not re.search(r'\b(venezuela|venezolan\w*|caracas|rep[uú]blica dominicana|dominican\w*|santo domingo)\b', title, re.IGNORECASE):
                category = 'INTERNACIONAL'
        news_items.append({
            'category': category,
            'title': title,
            'source': c['source'],
            **news_metadata(c),
            '_age_hours': c['age_hours'],
            '_seen_recently': c.get('_seen_recently', False),
        })

    efem_items = []
    for e in efemerides:
        txt = sanitize_final_headline(e['text'])
        if not txt.lower().startswith('en '):
            txt = f"En {e['year']}, {txt[0].lower()}{txt[1:]}" if len(txt) > 1 else txt
        if len(txt) > 94:
            head = txt[:94]
            cut = head.rsplit(',', 1)[0] if ',' in head else head.rsplit(' ', 1)[0]
            if len(cut) >= 45:
                txt = cut.rstrip(' ,;:')
            else:
                continue
        if txt.count('(') > txt.count(')'):
            txt = txt.rsplit('(', 1)[0].rstrip(' ,;:')
        if 32 <= len(txt) <= 94 and not re.search(r'[?¿¡!]', txt):
            efem_items.append({
                'category': EFEMERIDE_CATEGORY,
                'title': txt,
                'source': 'Wikimedia / Archivo 28E',
                'expiresAt': efemeride_expiry(),
            })
        if len(efem_items) >= 2:
            break

    return news_items, efem_items


def interleave_ticker(news_items, efem_items, max_news=24):
    """Ordena en carrusel equilibrado por categoría (más recientes primero) e intercala efemérides."""
    by_cat = {cat: [] for cat in VALID_CATEGORIES}
    for it in news_items:
        by_cat.setdefault(it['category'], []).append(it)

    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: (x.get('_seen_recently', False), x.get('_age_hours', 999)))

    rotated = []
    while len(rotated) < max_news:
        added_round = False
        for cat in VALID_CATEGORIES:
            bucket = by_cat.get(cat, [])
            if bucket and len(rotated) < max_news:
                item = bucket.pop(0)
                item.pop('_age_hours', None)
                item.pop('_seen_recently', None)
                rotated.append(item)
                added_round = True
        if not added_round:
            break

    if not efem_items:
        return rotated

    # Insertar efemérides espaciadas cada ~8 titulares
    final_list = []
    ef_idx = 0
    for idx, item in enumerate(rotated, start=1):
        final_list.append(item)
        if idx % 8 == 0 and ef_idx < len(efem_items):
            final_list.append(efem_items[ef_idx])
            ef_idx += 1

    while ef_idx < len(efem_items) and len(final_list) < max_news + 2:
        final_list.append(efem_items[ef_idx])
        ef_idx += 1

    return final_list


def fetch_fresh_ticker(use_llm=True, history=None, health=None):
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_local = datetime.datetime.now(LOCAL_TZ).date()

    candidates = collect_candidates(now_utc, history, health)
    efemerides = fetch_efemerides_candidates(today_local)

    news_items = []
    efem_items = []

    if use_llm and candidates:
        parsed, err = call_gemini_curate(candidates, efemerides, today_local)
        if isinstance(parsed, dict):
            news_items, efem_items = validate_gemini_items(parsed, candidates, efemerides)
            if len(news_items) < 16:
                print(f'[NEWS_SERVICE] Salida LLM incompleta ({len(news_items)}); complementando con respaldo B.', file=sys.stderr, flush=True)
                fallback_news, fallback_efems = build_fallback_items(candidates, efemerides)
                existing_titles = {n['title'].lower() for n in news_items}
                for fn in fallback_news:
                    if fn['title'].lower() not in existing_titles and len(news_items) < 22:
                        news_items.append(fn)
                        existing_titles.add(fn['title'].lower())
                if not efem_items:
                    efem_items = fallback_efems
        else:
            print(f'[NEWS_SERVICE] Usando respaldo B ({err}).', file=sys.stderr, flush=True)

    if not news_items:
        news_items, fallback_efems = build_fallback_items(candidates, efemerides)
        if not efem_items:
            efem_items = fallback_efems

    if not efem_items and efemerides:
        _, efem_items = build_fallback_items([], efemerides)

    return interleave_ticker(news_items, efem_items)


def write_ticker_cache(items):
    target = os.path.join(REPO_ROOT, 'stream-study', 'embarcadero', 'news-cache.js')
    payload = {'updatedAt': int(time.time() * 1000), 'items': items}
    temporary = target + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        handle.write('window.__radioNewsCache = ' + json.dumps(payload, ensure_ascii=False) + ';\n')
    os.replace(temporary, target)


def upload_to_firebase(items):
    cleaned = []
    for it in items:
        row = dict(it)
        row.pop('_age_hours', None)
        row.pop('_seen_recently', None)
        if row.get('title'):
            row['title'] = sanitize_final_headline(row['title'])
        cleaned.append(row)

    if os.environ.get('NEWS_PUBLISH_TRANSPORT') == 'rest':
        payload = {'updatedAt': int(time.time() * 1000), 'items': cleaned}
        request = urllib.request.Request(
            'https://yaire-591ca-default-rtdb.firebaseio.com/radio_state/news.json',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='PUT')
        with urllib.request.urlopen(request, timeout=30, context=SSL_CTX) as response:
            response.read()
        return ''

    publisher_path = os.path.join(SCRIPT_DIR, 'firebase-publisher.js')
    result = subprocess.run(
        [os.environ.get('NODE_BINARY', 'node'), publisher_path],
        input=json.dumps(cleaned, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def print_summary(items):
    print(f'\nTotal de titulares generados: {len(items)}')
    for idx, it in enumerate(items, start=1):
        src = it.get('source', '')
        title = it.get('title', '')
        print(f"  {idx:2d}. [{it['category']:16s}] ({len(title):2d}ch | {src}) {title}")


def _run_once(use_llm=True, dry_run=False, cache_only=False):
    print('[NEWS_SERVICE] Recopilando noticias recientes...', flush=True)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    history = load_news_history(now_utc)
    health = {}
    items = fetch_fresh_ticker(use_llm=use_llm, history=history, health=health)
    failed = [name for name, report in health.items() if not report['ok']]
    print(f'[NEWS_SERVICE] Fuentes consultadas: {len(health)}; con error: {len(failed)}', flush=True)
    if not dry_run:
        save_news_state('feed-health.json', {'checkedAt': now_utc.isoformat(), 'feeds': health})

    print_summary(items)
    if dry_run:
        print('\n[DRY-RUN] Modo prueba: no se publicó en Firebase.')
        return 0

    write_ticker_cache(items)
    if cache_only:
        print('[NEWS_SERVICE] Caché local actualizada.', flush=True)
        return 0
    upload_to_firebase(items)
    for item in items:
        if item.get('id'):
            history[item['id']] = now_utc.timestamp()
    save_news_state('history.json', history)
    print(f'\n[NEWS_SERVICE] Éxito: {len(items)} titulares actuales publicados en Firebase.', flush=True)
    return 0


def run_once(use_llm=True, dry_run=False, cache_only=False):
    if dry_run:
        return _run_once(use_llm=use_llm, dry_run=True)
    with news_update_lock():
        return _run_once(use_llm=use_llm, dry_run=False, cache_only=cache_only)


def parse_args(argv):
    parser = argparse.ArgumentParser(description='28E Radio — Actualizador unificado de noticias en vivo')
    parser.add_argument('--loop', '--watch', action='store_true', help='Ejecutar en bucle continuo')
    parser.add_argument('--once', action='store_true', help='Ejecutar una sola vez (predeterminado)')
    parser.add_argument('--dry-run', action='store_true', help='Mostrar resultado en consola sin escribir en Firebase')
    parser.add_argument('--cache-only', action='store_true', help='Actualizar solo la caché local sin publicar en Firebase')
    parser.add_argument('--skip-llm', action='store_true', help='Omitir Gemini y usar solo el respaldo RSS determinístico')
    parser.add_argument(
        '--interval',
        type=int,
        default=int(os.environ.get('NEWS_INTERVAL_SECONDS', '3600')),
        help='Segundos entre actualizaciones cuando se usa --loop (predeterminado: 3600)',
    )
    return parser.parse_args(argv)


def main(argv=None):
    load_dotenv()
    args = parse_args(argv)
    use_llm = not args.skip_llm

    if args.loop:
        print(f'[NEWS_SERVICE] Bucle activo cada {args.interval}s.', flush=True)
        while True:
            try:
                run_once(use_llm=use_llm, dry_run=args.dry_run, cache_only=args.cache_only)
            except Exception as e:
                print(f'[NEWS_SERVICE] Error actualizando noticias: {e}', file=sys.stderr, flush=True)
            time.sleep(max(300, args.interval))
    else:
        return run_once(use_llm=use_llm, dry_run=args.dry_run, cache_only=args.cache_only)


if __name__ == '__main__':
    sys.exit(main() or 0)
