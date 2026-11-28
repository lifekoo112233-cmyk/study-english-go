#!/usr/bin/env python3
"""CNN 주요 기사 수집기 (무료).

매일 GitHub Actions에서 실행:
  1) lite.cnn.com 첫 화면에서 주요 기사 링크를 순서대로 가져오고
  2) 기사 본문을 문장 단위로 나눈 뒤
  3) 무료 번역(Google 번역 공개 엔드포인트, 실패 시 MyMemory)으로 한국어 번역을 붙여
  4) data/news/<날짜>-<슬러그>.json 과 data/news/index.json 에 저장한다.

AI(OpenAI)는 쓰지 않는다. 문법 분석은 앱에서 「문」 버튼을 누를 때만 한다.

옵션:
  --count N      하루에 모을 기사 수 (기본 3)
  --max-sent N   기사당 최대 문장 수 (기본 25)
  --dry-run      파일을 쓰지 않고 결과만 출력
"""
import argparse, datetime, html, json, os, re, sys, time, urllib.parse, urllib.request

UA = 'Mozilla/5.0 (compatible; personal-study-bot/1.0)'
BASE = 'https://lite.cnn.com'
OUT = os.path.join('data', 'news')
KEEP = 90  # index.json 에 남길 기사 수
KST = datetime.timezone(datetime.timedelta(hours=9))


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 + i * 3)
    raise RuntimeError(f'GET {url} 실패: {last}')


def clean(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


# ---------- 1. 기사 목록 ----------
LINK_RE = re.compile(r'href="(/\d{4}/\d{2}/\d{2}/[^"#?]+)"[^>]*>(.*?)</a>', re.S)
SKIP_SECTIONS = ('/video/', '/gallery/', '/interactive/', '/live-news/', '/cnn-underscored/', '/weather/')


def top_links(n_max=40):
    page = get(BASE + '/')
    seen, out = set(), []
    for path, text in LINK_RE.findall(page):
        title = clean(text)
        if path in seen or not title or any(s in path for s in SKIP_SECTIONS):
            continue
        seen.add(path)
        out.append({'path': path, 'title': title})
        if len(out) >= n_max:
            break
    return out


# ---------- 2. 기사 본문 ----------
def article(path):
    page = get(BASE + path)
    m = re.search(r'<h2[^>]*class="[^"]*headline[^"]*"[^>]*>(.*?)</h2>', page, re.S) or re.search(r'<title>(.*?)</title>', page, re.S)
    title = clean(m.group(1)) if m else ''
    title = re.sub(r'\s*\|\s*CNN.*$', '', title)
    paras = [clean(p) for p in re.findall(r'<p[^>]*class="[^"]*paragraph[^"]*"[^>]*>(.*?)</p>', page, re.S)]
    if not paras:
        paras = [clean(p) for p in re.findall(r'<p[^>]*>(.*?)</p>', page, re.S)]
    bad = re.compile(r'^(Source: CNN|See Full Web Article|Updated |Published |CNN\s*—?$|Editor’s Note|Sign up|Read more|Related article)', re.I)
    paras = [p for p in paras if len(p) > 25 and not bad.search(p)]
    if paras:
        paras[0] = re.sub(r'^[A-Z][A-Za-z ,.\'-]{0,60}\(CNN\)\s*[—–-]+\s*', '', paras[0])  # "Washington (CNN) —" 제거
        paras[0] = re.sub(r'^CNN\s*[—–-]+\s*', '', paras[0])
    return title, paras


# ---------- 3. 문장 나누기 ----------
ABBR = r'(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Gen|Gov|Sen|Rep|Rev|Lt|Col|Sgt|Capt|Cmdr|Adm|Pres|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|No|vs|etc|Inc|Co|Corp|Ltd|U\.S|U\.K|U\.N|E\.U|D\.C|a\.m|p\.m|i\.e|e\.g)'


def sentences(text):
    t = re.sub(r'\b(' + ABBR + r')\.', lambda m: m.group(1).replace('.', '§') + '§', text)
    t = re.sub(r'(?<![A-Za-z])([A-Z])\.(?=\s?[A-Z])', r'\1§', t)  # J. K. Rowling 같은 이니셜
    t = re.sub(r'([.!?]["”’)]?)\s+(?=["“‘(]?[A-Z0-9])', '\\1\n', t)
    return [p.replace('§', '.').strip() for p in t.split('\n') if p.strip()]


# ---------- 4. 무료 번역 ----------
def tr_google(q):
    url = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q=' + urllib.parse.quote(q)
    j = json.loads(get(url, tries=2))
    return ''.join(seg[0] for seg in j[0] if seg and seg[0]).strip()


def tr_mymemory(q):
    url = 'https://api.mymemory.translated.net/get?langpair=en|ko&q=' + urllib.parse.quote(q)
    j = json.loads(get(url, tries=2))
    return ((j.get('responseData') or {}).get('translatedText') or '').strip()


def translate(q):
    for f in (tr_google, tr_mymemory):
        try:
            t = f(q)
            if t:
                return t
        except Exception as e:  # noqa: BLE001
            print('  번역 실패(' + f.__name__ + '):', e, file=sys.stderr)
        time.sleep(0.5)
    return ''


# ---------- 5. 저장 ----------
def slug_of(path):
    s = path.rstrip('/').split('/')[-1]
    if s in ('index.html', 'index'):
        s = path.rstrip('/').split('/')[-2]
    return re.sub(r'[^a-z0-9-]', '', s.lower())[:60] or 'article'


def load_index():
    p = os.path.join(OUT, 'index.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f).get('articles', [])
    except FileNotFoundError:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=int(os.environ.get('NEWS_COUNT', 3)))
    ap.add_argument('--max-sent', type=int, default=int(os.environ.get('NEWS_MAX_SENT', 25)))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    today = datetime.datetime.now(KST).strftime('%Y-%m-%d')
    idx = load_index()
    have = {x.get('url') for x in idx}
    links = top_links()
    print(f'첫 화면 링크 {len(links)}개')
    added = 0
    for ln in links:
        if added >= a.count:
            break
        url = 'https://www.cnn.com' + ln['path']
        if url in have:
            continue
        try:
            title, paras = article(ln['path'])
        except Exception as e:  # noqa: BLE001
            print('  본문 실패:', ln['path'], e)
            continue
        ss = [s for p in paras for s in sentences(p)]
        ss = [s for s in ss if 4 <= len(s.split()) <= 70]
        if len(ss) < 5:
            print('  문장이 너무 적어 건너뜀:', ln['path'], len(ss))
            continue
        ss = ss[:a.max_sent]
        title = title or ln['title']
        print(f'- {title}  ({len(ss)}문장)')
        if a.dry_run:
            print('  첫 문장:', ss[0])
            print('  번역 시험:', translate(ss[0]))
            added += 1
            continue
        sents = []
        for s in ss:
            sents.append({'en': s, 'ko': translate(s)})
            time.sleep(0.3)
        title_ko = translate(title)
        art = {
            'id': 'cnn-' + today + '-' + slug_of(ln['path'])[:40],
            'date': today, 'title': title, 'titleKo': title_ko,
            'source': 'CNN', 'url': url,
            'summaryKo': sents[0]['ko'] if sents else '',
            'created': int(time.time() * 1000), 'sentences': sents,
        }
        fn = f"{today}-{slug_of(ln['path'])}.json"
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, fn), 'w', encoding='utf-8') as f:
            json.dump(art, f, ensure_ascii=False, indent=1)
        idx.insert(0, {k: art[k] for k in ('id', 'date', 'title', 'titleKo', 'source', 'url', 'summaryKo')} | {'file': fn, 'n': len(sents)})
        have.add(url)
        added += 1
    if not a.dry_run:
        idx = idx[:KEEP]
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8') as f:
            json.dump({'updated': datetime.datetime.now(KST).isoformat(timespec='minutes'), 'articles': idx}, f, ensure_ascii=False, indent=1)
    print(f'새 기사 {added}개')
    if added == 0 and not links:
        sys.exit(1)


if __name__ == '__main__':
    main()
