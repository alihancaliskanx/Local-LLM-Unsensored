"""
Safe, Tor-only Webpage Content Extractor
Enforces strict Fail-Closed OPSEC: No traffic ever leaves the machine outside Tor.
Supports standard clearnet websites and Tor Hidden Services (.onion).
Read-only text extraction: Scripts, styles, iframes, and active content are stripped.
"""

import sys
import re
import socket
from typing import Optional, Dict, List

try:
    import requests
    from bs4 import BeautifulSoup
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError as e:
    sys.stderr.write(f"[OPSEC ERROR] Missing required Python package: {e}\n")
    sys.exit(1)

TOR_PROXIES = {
    "http": "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050"
}
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def check_tor_active(host: str = "127.0.0.1", port: int = 9050) -> bool:
    """Verifies that Tor SOCKS5 proxy is listening."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def resolve_repo_raw_url(url: str) -> List[str]:
    """
    Detects GitHub and GitLab repository landing URLs and derives direct raw README endpoints.
    Eliminates heavy JavaScript DOM bloat and delivers clean, full-text Markdown over Tor.
    """
    clean_url = url.split("?")[0].split("#")[0].rstrip("/")

    # 1. Direct raw github URL: already raw text
    if "raw.githubusercontent.com" in clean_url:
        return [clean_url]

    # 2. GitHub repo: https://github.com/owner/repo
    gh_match = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", clean_url)
    if gh_match:
        owner, repo = gh_match.group(1), gh_match.group(2)
        if owner.lower() not in ("topics", "features", "collections", "events", "trending", "marketplace"):
            return [
                f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md",
                f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README",
                f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
                f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md"
            ]

    # 3. GitLab repo: https://gitlab.../path/to/repo
    gl_match = re.match(r"^https?://(gitlab[^/]+)/(.+?)(?:\.git)?$", clean_url)
    if gl_match:
        host, path = gl_match.group(1), gl_match.group(2)
        if "/-/" not in path:
            return [
                f"https://{host}/{path}/-/raw/HEAD/README.md",
                f"https://{host}/{path}/-/raw/main/README.md",
                f"https://{host}/{path}/-/raw/master/README.md"
            ]

    return []


def fetch_page_text_tor(url: str, max_chars: int = 4500, timeout: Optional[int] = None) -> Optional[Dict[str, str]]:
    """
    Safely retrieves and extracts plain text from a webpage or .onion service over Tor SOCKS5h.
    Strips scripts, stylesheets, tracking pixels, forms, and navigational junk.
    Automatically routes GitHub and GitLab repositories to direct raw markdown for optimal fidelity.
    """
    if not check_tor_active():
        sys.stderr.write("[OPSEC ERROR] Tor SOCKS5 is offline. Page scraping aborted.\n")
        return None

    if not url.startswith("http://") and not url.startswith("https://"):
        return None

    is_onion = ".onion" in url.lower()
    effective_timeout = timeout if timeout is not None else (20 if is_onion else 12)
    verify_ssl = not is_onion

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/markdown,text/plain;q=0.8,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Proactive repository raw README routing
    candidate_raw_urls = resolve_repo_raw_url(url)
    for raw_endpoint in candidate_raw_urls:
        try:
            r_raw = requests.get(
                raw_endpoint,
                proxies=TOR_PROXIES,
                headers=headers,
                timeout=effective_timeout,
                verify=verify_ssl
            )
            # If 403 (common on gitlab/github when Tor exit nodes spoof browser UA), retry with clean client UA
            if r_raw.status_code == 403:
                r_raw = requests.get(
                    raw_endpoint,
                    proxies=TOR_PROXIES,
                    headers={"User-Agent": "curl/8.23.0", "Accept": "*/*"},
                    timeout=effective_timeout,
                    verify=verify_ssl
                )
            if r_raw.status_code == 200 and len(r_raw.text.strip()) > 30:
                clean_text = r_raw.text.strip()
                if len(clean_text) > max_chars:
                    clean_text = clean_text[:max_chars] + "\n...[truncated for context limits]..."
                display_name = url.split("://")[-1].rstrip("/")
                return {
                    "url": url,
                    "title": f"Repository Documentation ({display_name})",
                    "text": clean_text
                }
        except Exception:
            pass

    try:
        r = requests.get(
            url,
            proxies=TOR_PROXIES,
            headers=headers,
            timeout=effective_timeout,
            verify=verify_ssl
        )
        if r.status_code != 200:
            return None

        # Content type check: only parse HTML/text
        ct = r.headers.get("Content-Type", "")
        if "text/html" not in ct and "text/plain" not in ct:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Strip all active/harmful or irrelevant elements
        for element in soup(["script", "style", "noscript", "iframe", "header", "footer", "nav", "aside", "form"]):
            element.decompose()

        # Prioritize main article container if present
        target_container = soup.find("article") or soup.find("main") or soup.find("div", class_="content") or soup.body

        if not target_container:
            return None

        # Extract text paragraphs
        paragraphs = []
        for p in target_container.find_all(["p", "h1", "h2", "h3", "li", "pre"]):
            text = p.get_text(strip=True)
            if len(text) > 20:  # Skip tiny fragments
                paragraphs.append(text)

        full_text = "\n\n".join(paragraphs)
        if not full_text:
            full_text = target_container.get_text(separator="\n", strip=True)
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "\n...[truncated for context limits]..."

        title = soup.title.string.strip() if soup.title and soup.title.string else url

        return {
            "url": url,
            "title": title,
            "text": full_text
        }
    except Exception:
        return None
