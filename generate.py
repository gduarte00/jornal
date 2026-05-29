#!/usr/bin/env python3
"""
jornal pessoal — gerador diário
executa via github actions às 7h00 (horário de brasília)
"""

import os
import re
import sys
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz

from quotes import QUOTES

# ── configuração ──────────────────────────────────────────────────────────────

TMDB_KEY  = os.environ.get('TMDB_API_KEY', '')
TZ        = pytz.timezone('America/Sao_Paulo')
NOW       = datetime.now(TZ)
TODAY     = NOW.date()
TOMORROW  = TODAY + timedelta(days=1)

DAYS_PT   = ['segunda-feira', 'terça-feira', 'quarta-feira',
             'quinta-feira', 'sexta-feira', 'sábado', 'domingo']
MONTHS_PT = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
             'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

CINEMAS = {
    'capitolio': {
        'nome': 'cinemateca capitólio',
        'url':  'https://www.capitolio.org.br/programacao',
    },
    'paulo-amorim': {
        'nome': 'sala paulo amorim',
        'url':  'https://www.cinematecapauloamorim.com.br/programacao',
    },
    'sala-redencao': {
        'nome': 'sala redenção',
        'url':  'https://www.ufrgs.br/salaredencao/',
    },
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}


# ── notícias ──────────────────────────────────────────────────────────────────

def fetch_news():
    """
    Busca as 2 notícias mais relevantes do dia via Google News RSS.
    Prioriza notícias de Porto Alegre / RS, complementa com nacionais.
    """
    feeds = [
        'https://news.google.com/rss/search?q=Porto+Alegre&hl=pt-BR&gl=BR&ceid=BR:pt-419',
        'https://news.google.com/rss/search?q=Rio+Grande+do+Sul&hl=pt-BR&gl=BR&ceid=BR:pt-419',
        'https://news.google.com/rss/headlines/section/geo/BR?hl=pt-BR&gl=BR&ceid=BR:pt-419',
    ]

    seen, items = set(), []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:12]:
                # Google News adiciona "- Fonte" no fim do título — remove
                title = re.sub(r'\s*[-–]\s*[^-–]{2,40}$', '', entry.get('title', '')).strip()
                key   = title[:45].lower()
                if len(title) < 10 or key in seen:
                    continue
                seen.add(key)
                items.append({
                    'title':  title,
                    'link':   entry.get('link', '#'),
                    'source': entry.get('source', {}).get('title', ''),
                })
        except Exception as ex:
            print(f'[rss] erro em {url}: {ex}', file=sys.stderr)

    return items[:2]


# ── filmes ────────────────────────────────────────────────────────────────────

def get_poster(title: str) -> str:
    """Busca o poster do filme na API gratuita do TMDB."""
    if not TMDB_KEY:
        return ''
    try:
        r = requests.get(
            'https://api.themoviedb.org/3/search/movie',
            params={'query': title, 'api_key': TMDB_KEY, 'language': 'pt-BR'},
            timeout=8,
        ).json()
        results = r.get('results', [])
        if results and results[0].get('poster_path'):
            return f"https://image.tmdb.org/t/p/w300{results[0]['poster_path']}"
    except Exception:
        pass
    return ''


def scrape_cinemaempoa(date_str: str | None = None) -> dict:
    """
    Scrape cinemaempoa.com.br — agrega Capitólio, Paulo Amorim e Sala Redenção.
    Retorna: { cinema_id: { nome, url, filmes: [{title, times, poster}] } }
    """
    target = f'https://cinemaempoa.com.br/?date={date_str}' if date_str else 'https://cinemaempoa.com.br/'
    result = {cid: {**info, 'filmes': []} for cid, info in CINEMAS.items()}

    try:
        r = requests.get(target, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')

        for cid, info in CINEMAS.items():
            # palavras-chave para identificar a seção de cada cinema
            keywords = [w for w in info['nome'].split() if len(w) > 3]

            # encontra o header com o nome do cinema
            section_root = None
            for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'span']):
                text = tag.get_text(strip=True).lower()
                if sum(1 for kw in keywords if kw in text) >= 1:
                    # sobe até o container pai
                    section_root = tag.find_parent(['section', 'article', 'div'])
                    if not section_root:
                        section_root = tag.parent
                    break

            if not section_root:
                print(f'[cinema] seção não encontrada: {info["nome"]}')
                continue

            # extrai filmes — tenta seletores comuns de cards
            cards = (
                section_root.find_all(class_=re.compile(r'film|movie|card|item', re.I))
                or section_root.find_all(['article', 'li'])
                or [section_root]  # fallback: trata o container inteiro
            )

            for card in cards[:8]:
                title_el = card.find(['h2', 'h3', 'h4', 'strong', 'b'])
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if len(title) < 3:
                    continue

                # extrai horários com regex (padrão hh:mm ou hhhmm)
                raw  = card.get_text(' ')
                times = re.findall(r'\b\d{1,2}[h:]\d{2}\b', raw)

                result[cid]['filmes'].append({
                    'title':  title,
                    'times':  times,
                    'poster': get_poster(title),
                })

    except Exception as ex:
        print(f'[cinemaempoa] erro: {ex}', file=sys.stderr)

    return result


# ── quote ─────────────────────────────────────────────────────────────────────

def get_quote() -> str:
    idx = NOW.timetuple().tm_yday % len(QUOTES)
    return QUOTES[idx]


# ── renderização HTML ─────────────────────────────────────────────────────────

def fmt_date(d) -> str:
    return f"{DAYS_PT[d.weekday()]}, {d.day} de {MONTHS_PT[d.month - 1]} de {d.year}"


def html_film_card(film: dict) -> str:
    if film.get('poster'):
        poster = f'<img src="{film["poster"]}" alt="" class="poster" loading="lazy">'
    else:
        poster = '<div class="poster-ph"></div>'

    times = ' · '.join(film['times']) if film.get('times') else '—'

    return f'''
      <div class="film-card">
        {poster}
        <div class="film-meta">
          <span class="film-title">{film["title"].lower()}</span>
          <span class="film-times">{times}</span>
        </div>
      </div>'''


def html_cinema(cinema: dict) -> str:
    if not cinema['filmes']:
        return f'''
    <div class="cinema">
      <p class="cinema-name">{cinema["nome"]}</p>
      <p class="empty">sem sessões &middot; <a href="{cinema["url"]}" target="_blank" rel="noopener">ver programação</a></p>
    </div>'''
    cards = ''.join(html_film_card(f) for f in cinema['filmes'])
    return f'''
    <div class="cinema">
      <p class="cinema-name">{cinema["nome"]}</p>
      {cards}
    </div>'''


def build_html(news: list, today: dict, tomorrow: dict, quote: str) -> str:
    news_html = ''.join(f'''
    <article class="news-item">
      <a href="{n["link"]}" target="_blank" rel="noopener">{n["title"].lower()}</a>
      <span class="source">{n.get("source", "").lower()}</span>
    </article>''' for n in news)

    cinemas_today    = ''.join(html_cinema(c) for c in today.values())
    cinemas_tomorrow = ''.join(html_cinema(c) for c in tomorrow.values())

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0c0c0c">
<title>jornal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;1,400&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg:      #0c0c0c;
  --surface: #141414;
  --border:  #1e1e1e;
  --muted:   #444;
  --soft:    #777;
  --text:    #b8b8b8;
  --bright:  #dedede;
  --white:   #f0f0f0;
  --sans:    'Helvetica Neue', Helvetica, Arial, sans-serif;
  --serif:   'EB Garamond', Georgia, 'Times New Roman', serif;
}}

html {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--serif);
  font-size: 17px;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

body {{
  max-width: 440px;
  margin: 0 auto;
  padding: 56px 28px 80px;
}}

a {{ color: inherit; text-decoration: none; }}

/* ── data ── */
.date {{
  font-family: var(--sans);
  font-size: 10px;
  letter-spacing: 0.16em;
  color: var(--muted);
  text-transform: lowercase;
  padding-bottom: 48px;
}}

/* ── rótulos de seção ── */
.label {{
  display: block;
  font-family: var(--sans);
  font-size: 9px;
  letter-spacing: 0.22em;
  color: var(--muted);
  text-transform: lowercase;
  margin-bottom: 20px;
}}

/* ── notícias ── */
.news {{ margin-bottom: 52px; }}

.news-item {{
  padding: 18px 0;
  border-bottom: 1px solid var(--border);
}}

.news-item:first-child {{ padding-top: 0; }}

.news-item a {{
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.45;
  color: var(--bright);
  text-transform: lowercase;
  display: block;
  margin-bottom: 5px;
}}

.news-item a:hover {{ color: var(--white); }}

.source {{
  font-family: var(--serif);
  font-size: 13px;
  color: var(--muted);
  font-style: italic;
}}

/* ── filmes ── */
.films {{ margin-bottom: 52px; }}

.tab-bar {{
  display: flex;
  gap: 24px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 28px;
}}

.tab {{
  font-family: var(--sans);
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: lowercase;
  color: var(--muted);
  padding-bottom: 10px;
  background: none;
  border: none;
  border-bottom: 1px solid transparent;
  margin-bottom: -1px;
  cursor: pointer;
  -webkit-appearance: none;
}}

.tab.active {{
  color: var(--bright);
  border-bottom-color: var(--bright);
}}

.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}

.cinema {{ margin-bottom: 40px; }}

.cinema-name {{
  font-family: var(--sans);
  font-size: 9px;
  letter-spacing: 0.2em;
  color: var(--muted);
  text-transform: lowercase;
  margin-bottom: 16px;
}}

.film-card {{
  display: flex;
  gap: 14px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
  align-items: flex-start;
}}

.film-card:last-child {{ border-bottom: none; }}

.poster {{
  width: 48px;
  height: 72px;
  object-fit: cover;
  flex-shrink: 0;
  display: block;
}}

.poster-ph {{
  width: 48px;
  height: 72px;
  background: var(--surface);
  flex-shrink: 0;
}}

.film-meta {{
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding-top: 2px;
}}

.film-title {{
  font-family: var(--sans);
  font-size: 12px;
  color: var(--bright);
  line-height: 1.4;
  text-transform: lowercase;
}}

.film-times {{
  font-family: var(--serif);
  font-size: 13px;
  color: var(--soft);
  font-style: italic;
}}

.empty {{
  font-family: var(--serif);
  font-size: 14px;
  color: var(--muted);
  font-style: italic;
}}

.empty a {{ color: var(--soft); }}
.empty a:hover {{ color: var(--text); }}

/* ── quote ── */
.quote {{
  border-top: 1px solid var(--border);
  padding-top: 40px;
}}

.quote p {{
  font-family: var(--serif);
  font-size: 15px;
  line-height: 1.75;
  color: var(--soft);
  font-style: italic;
}}
</style>
</head>
<body>

<p class="date">{fmt_date(TODAY)}</p>

<span class="label">notícias</span>
<section class="news">
{news_html}
</section>

<span class="label">em cartaz</span>
<section class="films">
  <div class="tab-bar">
    <button class="tab active" onclick="go(event,'hoje')">hoje</button>
    <button class="tab"        onclick="go(event,'amanha')">amanhã</button>
  </div>
  <div id="hoje"   class="tab-panel active">{cinemas_today}</div>
  <div id="amanha" class="tab-panel">{cinemas_tomorrow}</div>
</section>

<div class="quote">
  <p>&#8220;{quote}&#8221;</p>
</div>

<script>
function go(e, id) {{
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.remove('active'); }});
  e.currentTarget.classList.add('active');
  document.getElementById(id).classList.add('active');
}}
</script>

</body>
</html>'''


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('buscando notícias...')
    news = fetch_news()
    print(f'  {len(news)} notícia(s) encontrada(s)')

    print('buscando filmes de hoje...')
    today_films = scrape_cinemaempoa()

    print('buscando filmes de amanhã...')
    tomorrow_films = scrape_cinemaempoa(TOMORROW.isoformat())

    quote = get_quote()

    print('gerando index.html...')
    html = build_html(news, today_films, tomorrow_films, quote)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print('✓ index.html gerado')
