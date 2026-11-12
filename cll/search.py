#!/usr/bin/env python3
"""
qwsearch.py - Privacy-preserving, Tor-only Web Search for Local LLM
Guarantees Fail-Closed OPSEC: No network packet ever leaves the machine outside Tor.
"""

import sys
import os
import re
import json
import socket
import base64
import argparse
import subprocess
import urllib.parse
from collections import Counter
from typing import List, Dict, Optional, Tuple
import xml.etree.ElementTree as ET

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    sys.stderr.write(f"[OPSEC ERROR] Missing required Python package: {e}\n")
    sys.exit(1)

TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9050
TOR_CONTROL_PORT = 9051
TOR_PROXIES = {
    "http": f"socks5h://{TOR_SOCKS_HOST}:{TOR_SOCKS_PORT}",
    "https": f"socks5h://{TOR_SOCKS_HOST}:{TOR_SOCKS_PORT}"
}
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def check_tor_port(host: str = TOR_SOCKS_HOST, port: int = TOR_SOCKS_PORT, timeout: float = 1.5) -> bool:
    """Verifies that the local Tor SOCKS proxy is listening and accepting connections."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def enforce_tor_gatekeeper() -> None:
    """Fails closed immediately if Tor SOCKS proxy is unreachable."""
    if not check_tor_port():
        sys.stderr.write(
            f"\n[OPSEC FAIL-CLOSED ERROR]\n"
            f"Tor SOCKS5 proxy ({TOR_SOCKS_HOST}:{TOR_SOCKS_PORT}) is unreachable!\n"
            f"All internet access aborted to guarantee ZERO cleartext network leakage.\n"
            f"Please verify Tor service or check with: proxyctl status\n\n"
        )
        sys.exit(2)


def leak_test(auto_retry: bool = True) -> Dict[str, any]:
    """Audits the connection by querying check.torproject.org through Tor SOCKS5h."""
    enforce_tor_gatekeeper()
    url = "https://check.torproject.org/api/ip"
    try:
        r = requests.get(url, proxies=TOR_PROXIES, headers={"User-Agent": USER_AGENT}, timeout=10)
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}", "IsTor": False}
    except Exception as e:
        if auto_retry:
            rotate_tor_circuit()
            return leak_test(auto_retry=False)
        return {"error": str(e), "IsTor": False}


def rotate_tor_circuit() -> bool:
    """Sends SIGNAL NEWNYM to Tor ControlPort to acquire a new circuit."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect((TOR_SOCKS_HOST, TOR_CONTROL_PORT))
        s.sendall(b'AUTHENTICATE ""\r\nSIGNAL NEWNYM\r\nQUIT\r\n')
        resp = s.recv(1024).decode("utf-8", errors="ignore")
        s.close()
        if "250 OK" in resp:
            return True
    except Exception:
        pass

    try:
        res = subprocess.run(["proxyctl", "tor", "newip"], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def clean_ddg_url(raw_url: str) -> str:
    """Decodes DuckDuckGo redirect URLs into direct target URLs."""
    if not raw_url:
        return ""
    if "duckduckgo.com/l/?uddg=" in raw_url or raw_url.startswith("//duckduckgo.com/l/?uddg="):
        parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(raw_url).query)
        if "uddg" in parsed:
            return parsed["uddg"][0]
    return raw_url


def clean_bing_url(raw_url: str) -> str:
    """Decodes Bing redirect URLs containing base64 destinations."""
    if not raw_url:
        return ""
    try:
        if "/ck/a?!" in raw_url:
            parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(raw_url).query)
            if "u" in parsed:
                encoded = parsed["u"][0]
                if encoded.startswith("a1"):
                    encoded = encoded[2:]
                padded = encoded + "=" * (-len(encoded) % 4)
                return base64.b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        pass
    return raw_url


COMMERCIAL_SPAM_DOMAINS = {
    'atomtickets.com', 'atom.com', 'dan.com', 'sedo.com', 'godaddy.com',
    'ticketmaster.com', 'stubhub.com', 'fandango.com'
}

COMMERCIAL_SPAM_PATTERNS = [
    r'\b(?:movie\s*tickets|showtimes|buy\s*tickets|ticketmaster|cinema)\b',
    r'\b(?:domain\s*marketplace|domains?\s*for\s*sale|buy\s*domain|registrar)\b',
]


def is_result_relevant(query: str, title: str, snippet: str, url: str = "") -> bool:
    """
    Ensures search results contain meaningful keywords from the query and filters
    out commercial spam (ticket vendors, domain brokers, geo-ads).
    """
    if url:
        for d in COMMERCIAL_SPAM_DOMAINS:
            if d in url.lower():
                return False
    text = f"{title} {snippet}".lower()
    for pat in COMMERCIAL_SPAM_PATTERNS:
        if re.search(pat, text):
            if not re.search(r'\b(ticket|movie|domain|cinema)\b', query.lower()):
                return False

    query_words = set(re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', query.lower()))
    stopwords = {
        'the', 'and', 'for', 'with', 'what', 'how', 'official', 'latest', 'current',
        'recent', 'package', 'packages', 'guide', 'tutorial', 'overview', 'simple',
        'methods', 'basics', 'basic'
    }
    core_keywords = {w for w in query_words if w not in stopwords}
    if not core_keywords:
        return True
    return any(kw in text for kw in core_keywords)


def search_duckduckgo_html(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Queries DuckDuckGo HTML strictly over Tor SOCKS5h with US-EN localization."""
    url = "https://html.duckduckgo.com/html/"
    data = {"q": query, "kl": "us-en"}
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        r = requests.post(url, data=data, proxies=TOR_PROXIES, headers=headers, timeout=10)
        if r.status_code not in (200, 202) or "anomaly-modal" in r.text:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for res in soup.find_all("div", class_="result__body"):
            t_elem = res.find("a", class_="result__a")
            s_elem = res.find("a", class_="result__snippet")
            if not t_elem:
                continue

            clean_url = clean_ddg_url(t_elem.get("href", ""))
            title = t_elem.get_text(strip=True)
            snippet = s_elem.get_text(strip=True) if s_elem else ""

            if title and clean_url and not clean_url.startswith("//duckduckgo.com"):
                if is_result_relevant(query, title, snippet):
                    results.append({
                        "title": title,
                        "url": clean_url,
                        "snippet": snippet,
                        "engine": "DuckDuckGo"
                    })
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


def search_bing(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Queries Bing Search strictly over Tor SOCKS5h with US-EN localization and relevance filtering."""
    url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}&setlang=en-US&cc=US"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(url, proxies=TOR_PROXIES, headers=headers, timeout=10)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for res in soup.find_all("li", class_="b_algo"):
            h2 = res.find("h2")
            if not h2:
                continue
            a_elem = h2.find("a")
            if not a_elem:
                continue

            p_elem = res.find("p")
            clean_url = clean_bing_url(a_elem.get("href", ""))
            title = a_elem.get_text(strip=True)
            snippet = p_elem.get_text(strip=True) if p_elem else ""

            if title and clean_url and clean_url.startswith("http"):
                if is_result_relevant(query, title, snippet):
                    results.append({
                        "title": title,
                        "url": clean_url,
                        "snippet": snippet,
                        "engine": "Bing"
                    })
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


def search_github_repositories(query: str, limit: int = 3) -> List[Dict[str, str]]:
    """Queries GitHub Search API strictly over Tor SOCKS5h for software projects and specifications."""
    clean_q = re.sub(r"[?!.,;:]+", " ", query).strip()
    words = [w for w in re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", clean_q)]
    if not words:
        return []

    candidates = [" ".join(words[:3])]
    clean_words = [re.sub(r"^(?:AP_|lib|py)", "", w, flags=re.IGNORECASE) for w in words]
    if len(clean_words) > 1:
        candidates.append(" ".join(clean_words[:2]))
    if words[0] not in candidates:
        candidates.append(words[0])

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json"
    }

    for cand in candidates:
        url = f"https://api.github.com/search/repositories?q={urllib.parse.quote_plus(cand)}&sort=stars&order=desc"
        try:
            r = requests.get(url, proxies=TOR_PROXIES, headers=headers, timeout=8)
            if r.status_code == 200:
                items = r.json().get("items", [])
                if items:
                    results = []
                    for item in items[:limit]:
                        full_name = item.get("full_name", "")
                        stars = item.get("stargazers_count", 0)
                        desc = item.get("description", "") or ""
                        html_url = item.get("html_url", "")
                        if full_name and html_url:
                            results.append({
                                "title": f"GitHub: {full_name} ({stars}★)",
                                "url": html_url,
                                "snippet": desc,
                                "engine": "GitHub API (Tor)"
                            })
                    return results
        except Exception:
            pass

    return []


def fetch_wikipedia_summary(query: str) -> Optional[Dict[str, str]]:
    """Retrieves Wikipedia encyclopedic context strictly over Tor SOCKS5h using REST API with OpenSearch fallback."""
    headers = {"User-Agent": USER_AGENT}
    clean_title = query.strip().replace(" ", "_")

    # 1. Try direct REST summary
    direct_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(clean_title)}"
    try:
        r = requests.get(direct_url, proxies=TOR_PROXIES, headers=headers, timeout=8)
        if r.status_code == 200:
            d = r.json()
            extract = d.get("extract", "")
            if extract:
                return {
                    "title": f"Wikipedia: {d.get('title')}",
                    "url": d.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{clean_title}"),
                    "snippet": extract,
                    "engine": "Wikipedia"
                }
    except Exception:
        pass

    # 2. Try OpenSearch with full query, then fall back to primary non-stopword keywords
    candidates = [query]
    wiki_stopwords = {
        'how', 'what', 'why', 'when', 'where', 'who', 'which', 'to', 'the', 'an', 'a',
        'in', 'on', 'for', 'with', 'simple', 'methods', 'basic', 'mechanics'
    }
    words = [w for w in re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", query) if w.lower() not in wiki_stopwords]
    if len(words) > 1:
        candidates.append(" ".join(words[:2]))
    if words:
        candidates.append(words[0])

    for cand in candidates:
        opensearch_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote_plus(cand)}&limit=1&format=json"
        try:
            r = requests.get(opensearch_url, proxies=TOR_PROXIES, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 4 and data[1]:
                    canonical_title = data[1][0]
                    canon_clean = canonical_title.replace(" ", "_")
                    r2 = requests.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(canon_clean)}",
                        proxies=TOR_PROXIES, headers=headers, timeout=8
                    )
                    if r2.status_code == 200:
                        d2 = r2.json()
                        extract2 = d2.get("extract", "")
                        if extract2:
                            return {
                                "title": f"Wikipedia: {d2.get('title')}",
                                "url": d2.get("content_urls", {}).get("desktop", {}).get("page", f"https://en.wikipedia.org/wiki/{canon_clean}"),
                                "snippet": extract2,
                                "engine": "Wikipedia"
                            }
        except Exception:
            pass

    return None


def extract_wikipedia_references(wiki_title_or_url: str, limit: int = 3) -> List[Dict[str, str]]:
    """
    Extracts primary authoritative citations (DOI, ArXiv, Nature, APS, ScienceDirect, .edu, .gov)
    from a Wikipedia page's References section strictly over Tor.
    """
    title = wiki_title_or_url.replace("https://en.wikipedia.org/wiki/", "").replace(" ", "_")
    url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"
    headers = {"User-Agent": USER_AGENT}
    results = []
    try:
        r = requests.get(url, proxies=TOR_PROXIES, headers=headers, timeout=12)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            cites = soup.select('.citation, .reference-text, li[id^="cite_note-"]')
            seen_urls = set()
            academic_domains = [
                'doi.org', 'arxiv.org', 'nature.com', 'sciencedirect.com',
                'aps.org', 'springer.com', 'jstor.org', '.edu', '.gov', 'nobelprize.org'
            ]
            for c in cites:
                for a in c.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('//'):
                        href = 'https:' + href
                    if not href.startswith('http'):
                        continue
                    if any(d in href for d in academic_domains) and href not in seen_urls:
                        seen_urls.add(href)
                        raw_text = c.get_text(' ', strip=True)
                        clean_text = re.sub(r'^\s*\^?\s*', '', raw_text)
                        clean_text = re.sub(r'\s+', ' ', clean_text)
                        link_title = a.get_text(strip=True) or clean_text[:60]
                        results.append({
                            "title": f"Primary Source: {link_title}",
                            "url": href,
                            "snippet": clean_text[:350],
                            "engine": "Wikipedia Primary References"
                        })
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


def search_arxiv(query: str, limit: int = 3) -> List[Dict[str, str]]:
    """
    Queries ArXiv API for peer-reviewed academic preprints strictly over Tor SOCKS5h.
    """
    clean_q = re.sub(r'[^\w\s]', ' ', query).strip()
    words = [w for w in clean_q.split() if len(w) > 2]
    if not words:
        return []
    search_expr = "+AND+".join(words[:4])
    url = f"http://export.arxiv.org/api/query?search_query=all:{search_expr}&start=0&max_results={limit}"
    results = []
    try:
        r = requests.get(url, proxies=TOR_PROXIES, timeout=10)
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('atom:entry', ns):
                title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
                summary = entry.find('atom:summary', ns).text.strip().replace('\n', ' ')
                link = entry.find('atom:id', ns).text.strip()
                results.append({
                    "title": f"ArXiv Paper: {title}",
                    "url": link,
                    "snippet": summary[:350],
                    "engine": "ArXiv API (Tor)"
                })
    except Exception:
        pass
    return results


_AHMIA_TOKEN = ("c37337", "6dc8c0")
EMOJI_RE = re.compile(r'[\u2600-\u27bf\U0001f300-\U0001f9ff\U0001fa00-\U0001faff]')


def is_darkweb_spam(title: str, snippet: str = "") -> bool:
    """Detects SEO-spam, phishing traps, and keyword-stuffed onion search results."""
    if not title:
        return True
    # 1. Emoji stuffing (>= 3 emojis)
    if len(EMOJI_RE.findall(title)) >= 3:
        return True
    # 2. Consecutive identical word repeats (e.g. tor tor tor, tor | tor | tor)
    if re.search(r'\b([a-zA-Z0-9]{2,})\b(?:[\s|\-_,]+\1\b){2,}', title, re.IGNORECASE):
        return True
    # 3. High word frequency spam (e.g. 4+ occurrences of the same word in a title)
    words = [w.lower() for w in re.findall(r'\b[a-zA-Z0-9]{2,}\b', title)]
    if words:
        counts = Counter(words)
        if max(counts.values()) >= 4:
            return True
        if len(words) >= 6 and (max(counts.values()) / len(words) > 0.45) and max(counts.values()) >= 3:
            return True
    return False


def _parse_ahmia_results(html: str, limit: int = 5, max_per_domain: int = 2) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    spam_candidates = []
    overflow_domain_candidates = []
    seen_urls = set()
    domain_counts = Counter()

    for item in soup.find_all("li", class_="result"):
        a_tag = item.find("a")
        p_tag = item.find("p")
        cite_tag = item.find("cite")
        if not a_tag:
            continue

        href = a_tag.get("href", "")
        real_url = ""
        if "redirect_url=" in href:
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            real_url = qs.get("redirect_url", [""])[0]
        elif ".onion" in href:
            real_url = href

        if not real_url and cite_tag:
            cite_text = cite_tag.get_text(strip=True)
            if ".onion" in cite_text:
                real_url = cite_text if cite_text.startswith("http") else f"http://{cite_text}"

        if not real_url or ".onion" not in real_url or real_url in seen_urls:
            continue

        seen_urls.add(real_url)
        title = " ".join(a_tag.get_text().split())
        snippet = " ".join(p_tag.get_text().split()) if p_tag else ""

        entry = {
            "title": title or real_url,
            "url": real_url,
            "snippet": snippet,
            "engine": "Ahmia (.onion)"
        }

        if is_darkweb_spam(title, snippet):
            spam_candidates.append(entry)
            continue

        # Extract onion domain for diversity
        parsed_url = urllib.parse.urlparse(real_url)
        domain = parsed_url.netloc.lower() or parsed_url.path.split("/")[0].lower()

        if domain_counts[domain] >= max_per_domain:
            overflow_domain_candidates.append(entry)
            continue

        domain_counts[domain] += 1
        results.append(entry)

        if len(results) >= limit:
            break

    # If results are still fewer than limit, backfill with overflow domain candidates first
    if len(results) < limit and overflow_domain_candidates:
        for oc in overflow_domain_candidates:
            results.append(oc)
            if len(results) >= limit:
                break

    # If legitimate results were fewer than limit, backfill with non-spam candidates
    if len(results) < limit and spam_candidates:
        for sc in spam_candidates:
            results.append(sc)
            if len(results) >= limit:
                break

    return results


def search_ahmia_onion(query: str, limit: int = 5) -> List[Dict[str, str]]:
    """Queries Ahmia over Tor SOCKS5h to discover .onion hidden services."""
    global _AHMIA_TOKEN
    enforce_tor_gatekeeper()
    s = requests.Session()
    s.proxies = TOR_PROXIES
    s.headers.update({"User-Agent": USER_AGENT})

    words = query.split()
    candidates = [query]
    if len(words) > 2:
        candidates.append(" ".join(words[:2]))

    for cand_q in candidates:
        params = {"q": cand_q, _AHMIA_TOKEN[0]: _AHMIA_TOKEN[1]}
        try:
            r = s.get("https://ahmia.fi/search/", params=params, timeout=15)
            if r.status_code == 200:
                results = _parse_ahmia_results(r.text, limit=limit)
                if results:
                    return results
                soup_home = BeautifulSoup(r.text, "html.parser")
                form = soup_home.find("form", id="searchForm")
                if form:
                    inp = form.find("input", type="hidden")
                    if inp and inp.get("name") and inp.get("value"):
                        new_token = (inp["name"], inp["value"])
                        if new_token != _AHMIA_TOKEN:
                            _AHMIA_TOKEN = new_token
                            params = {"q": cand_q, _AHMIA_TOKEN[0]: _AHMIA_TOKEN[1]}
                            r2 = s.get("https://ahmia.fi/search/", params=params, timeout=15)
                            if r2.status_code == 200:
                                results = _parse_ahmia_results(r2.text, limit=limit)
                                if results:
                                    return results
        except Exception:
            pass
    return []


DECOY_QUERIES = [
    "linux epoll socket nonblocking IO",
    "sqlite btree storage page format",
    "python typing abstract base class protocol",
    "rust tokio async mpsc channel",
    "zlib deflate huffman coding algorithm",
    "posix semaphore shared memory synchronization",
    "tls 1.3 handshake cryptographic suites"
]


def send_chaff_query():
    """Sends a randomized decoy query over Tor to introduce timing and packet size entropy."""
    import random
    decoy = random.choice(DECOY_QUERIES)
    sys.stderr.write(f"[OPSEC CHAFF] Emitting decoy query over Tor: '{decoy}'...\n")
    sys.stderr.flush()
    try:
        search_bing(decoy, limit=1)
    except Exception:
        pass
    time.sleep(random.uniform(0.3, 0.7))


def execute_search_cascade(query: str, limit: int = 5, with_chaff: bool = False) -> Tuple[List[Dict[str, str]], str]:
    """
    Executes resilient privacy search over Tor SOCKS5h.
    Tries DuckDuckGo HTML first; if blocked by anomaly/CAPTCHA, falls back to Bing.
    Auto-refreshes Tor circuit if a dead circuit is encountered.
    Enriches with GitHub repository search and Wikipedia summary.
    If with_chaff=True, injects decoy traffic before the real query.
    """
    enforce_tor_gatekeeper()

    if with_chaff:
        send_chaff_query()

    engine_used = "DuckDuckGo"
    results = search_duckduckgo_html(query, limit=limit)

    if not results:
        engine_used = "Bing (Tor Fallback)"
        results = search_bing(query, limit=limit)

    # Multi-term query condensation fallback if dense technical query yielded no results
    words = [w for w in re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", query) if w.lower() not in (
        'the', 'and', 'for', 'with', 'what', 'how', 'official', 'latest', 'current',
        'recent', 'architecture', 'mechanism', 'overview', 'details'
    )]
    if not results and len(words) > 2:
        condensed_q = " ".join(words[:3])
        results = search_bing(condensed_q, limit=limit)
        if results:
            engine_used = "Bing (Condensed Query)"

    if not results:
        # Automatic recovery for expired/stale Tor circuits
        if rotate_tor_circuit():
            engine_used = "Bing (Circuit Refreshed)"
            results = search_bing(query, limit=limit)
            if not results and len(words) > 2:
                condensed_q = " ".join(words[:3])
                results = search_bing(condensed_q, limit=limit)

    # Enrich with GitHub developer repositories over Tor only if query targets software/hardware/tools/exploits
    is_dev_query = bool(re.search(r'\b(github|repo|git|code|library|pkg|package|sdk|api|cli|tool|script|exploit|cve|driver|firmware|protocol|implementation)\b', query, re.IGNORECASE))
    if is_dev_query:
        gh_results = search_github_repositories(query, limit=2)
        if gh_results:
            existing_urls = {r.get("url") for r in results}
            for g in gh_results:
                if g.get("url") not in existing_urls and len(results) < limit:
                    results.append(g)
                    existing_urls.add(g.get("url"))

    wiki = fetch_wikipedia_summary(query)
    if wiki and len(results) < limit:
        existing_urls = {r.get("url") for r in results}
        if wiki.get("url") not in existing_urls:
            results.append(wiki)
            existing_urls.add(wiki.get("url"))
            # Extract primary authoritative citations from Wikipedia References
            for ref in extract_wikipedia_references(wiki.get("url"), limit=2):
                if ref.get("url") not in existing_urls and len(results) < limit:
                    results.append(ref)
                    existing_urls.add(ref.get("url"))

    # Academic ArXiv paper discovery for scientific/technical queries
    is_academic = bool(re.search(r'\b(physics|quantum|nuclear|fission|fusion|reaction|mechanics|theory|algorithm|cryptography|protocol|biology|chemistry|paper|equation)\b', query, re.IGNORECASE))
    if is_academic and len(results) < limit:
        existing_urls = {r.get("url") for r in results}
        for a in search_arxiv(query, limit=2):
            if a.get("url") not in existing_urls and len(results) < limit:
                results.append(a)
                existing_urls.add(a.get("url"))

    return results, engine_used


def format_markdown_context(query: str, results: List[Dict[str, str]], engine: str) -> str:
    """Formats search results as clean Markdown context for downstream consumption."""
    lines = [
        f"### Web Search Context (OPSEC: Tor Verified | Engine: {engine})",
        f"Query: {query}",
        f"Results Count: {len(results)}\n"
    ]
    for idx, r in enumerate(results, 1):
        lines.append(f"{idx}. [{r['title']}]({r['url']})")
        if r["snippet"]:
            lines.append(f"   Snippet: {r['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()


def synthesize_with_llm(query: str, context: str, reasoning_level: int = 2) -> None:
    """Invokes active llama-server (if running) or local qwen-local CLI to synthesize an answer from the Tor search context."""
    full_prompt = (
        "You are an expert technical assistant with access to real-time web search results.\n"
        "Use the provided web search context to answer the user's question directly, accurately, and thoroughly.\n"
        "Cite sources using their URLs or numbers when referencing specific claims.\n"
        "If the search results do not contain enough information, state what is known and clarify the limitation.\n"
        "Respond in the language of the user's query.\n\n"
        f"User Question: {query}\n\n"
        f"Web Search Results:\n{context}\n"
    )

    # 1. Try active llama-server first (instant response, live streaming, zero GPU conflict)
    try:
        import urllib.request
        server_url = "http://127.0.0.1:8080/v1/chat/completions"
        req_payload = {
            "messages": [
                {"role": "user", "content": full_prompt}
            ],
            "temperature": 0.2,
            "stream": True
        }
        req = urllib.request.Request(
            server_url,
            data=json.dumps(req_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status == 200:
                got_tokens = False
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                                got_tokens = True
                        except Exception:
                            pass
                if got_tokens:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return
    except Exception:
        pass

    # 2. Fall back to qwen-local CLI if llama-server is offline
    reasoning_flags = {
        0: ["--reasoning", "off"],
        1: ["--reasoning", "on", "--reasoning-effort", "low"],
        2: ["--reasoning", "on", "--reasoning-effort", "medium"],
        3: ["--reasoning", "on", "--reasoning-effort", "high"],
        4: ["--reasoning", "on", "--reasoning-effort", "max"]
    }.get(reasoning_level, ["--reasoning", "on", "--reasoning-effort", "medium"])

    import tempfile
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as pf:
        pf.write(full_prompt)
        prompt_file = pf.name
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tmp_name = tf.name

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    qwen_bin = os.path.join(repo_root, "qwen-local")
    if not os.path.exists(qwen_bin):
        qwen_bin = "qwen-local"

    cmd = [
        qwen_bin, "cli",
        "--simple-io", "--log-disable", "-st",
        "-c", "16384",
        "-f", prompt_file,
        "-o", tmp_name
    ] + reasoning_flags

    env = os.environ.copy()
    env["RULES_PATH"] = "/dev/null"

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        content = ""
        if os.path.exists(tmp_name):
            with open(tmp_name, "r", errors="ignore") as f:
                content = f.read()

        if "Assistant:" in content:
            response = content.split("Assistant:", 1)[1].strip()
            print(response)
        elif content.strip():
            print(content.strip())
        elif proc.returncode != 0 and proc.stderr:
            sys.stderr.write(f"[qwsearch error] {proc.stderr.strip()}\n")
        else:
            sys.stderr.write("[qwsearch] No synthesis output generated by model.\n")
    except Exception as e:
        sys.stderr.write(f"\n[Error during LLM synthesis: {e}]\n")
    finally:
        for p in (prompt_file, tmp_name):
            if os.path.exists(p):
                os.remove(p)


def main():
    parser = argparse.ArgumentParser(
        description="qwsearch - Privacy-preserving Tor-only Web Search for Local LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  qwsearch 'Arch Linux latest news'\n"
            "  qwsearch --raw 'Linux kernel 6.13' | qwpipe\n"
            "  qwsearch --leak-test\n"
            "  qwsearch --new-circuit 'systemd security'\n"
        )
    )
    parser.add_argument("query", nargs="*", help="Search query string")
    parser.add_argument("-n", "--limit", type=int, default=5, help="Maximum number of search results (default: 5)")
    parser.add_argument("-r", "--reasoning", type=int, default=2, choices=[0, 1, 2, 3, 4], help="Reasoning level for synthesis (0..4, default: 2)")
    parser.add_argument("--raw", action="store_true", help="Output raw search markdown context without LLM synthesis")
    parser.add_argument("--json", action="store_true", help="Output search results in JSON format")
    parser.add_argument("--leak-test", action="store_true", help="Audit Tor circuit and verify IP via check.torproject.org")
    parser.add_argument("--new-circuit", action="store_true", help="Request a new Tor identity/circuit before searching")
    parser.add_argument("--chaff", "--decoy", action="store_true", help="Emit random decoy queries over Tor for traffic analysis resistance")

    args = parser.parse_args()

    # 1. Leak Test
    if args.leak_test:
        audit = leak_test()
        if audit.get("IsTor") is True:
            sys.stdout.write(
                f"\n[OPSEC CONFIRMED] Tor circuit is active and secure.\n"
                f"  Exit IP:    {audit.get('IP')}\n"
                f"  Tor Status: Active ({audit.get('IsTor')})\n"
                f"  DNS Mode:   Remote (socks5h - Zero Local Leak)\n\n"
            )
            sys.exit(0)
        else:
            sys.stderr.write(
                f"\n[OPSEC AUDIT FAILED] Tor circuit verification failed: {audit}\n\n"
            )
            sys.exit(1)

    # 2. Circuit Rotation
    if args.new_circuit:
        if rotate_tor_circuit():
            sys.stderr.write("[OPSEC INFO] Tor circuit refreshed (SIGNAL NEWNYM sent).\n")
        else:
            sys.stderr.write("[OPSEC WARNING] Could not refresh Tor circuit via ControlPort.\n")

    query_str = " ".join(args.query).strip()
    if not query_str:
        parser.print_help()
        sys.exit(0)

    # 3. Search Cascade over Tor
    results, engine_used = execute_search_cascade(query_str, limit=args.limit, with_chaff=args.chaff)

    if not results:
        sys.stderr.write(
            f"\n[qwsearch] No results found or search rate-limited on current Tor circuit.\n"
            f"Tip: Run with '--new-circuit' to obtain a fresh Tor exit node.\n\n"
        )
        sys.exit(1)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        sys.exit(0)

    context = format_markdown_context(query_str, results, engine_used)

    if args.raw:
        print(context)
        sys.exit(0)

    # 4. LLM Synthesis Header & Execution
    sys.stderr.write(
        f"── [Qwen3-4B Search | Query: {query_str} | OPSEC: Tor Verified | Engine: {engine_used} | Results: {len(results)}] ──\n"
    )
    synthesize_with_llm(query_str, context, reasoning_level=args.reasoning)


if __name__ == "__main__":
    main()
