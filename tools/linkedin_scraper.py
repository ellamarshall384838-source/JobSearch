"""
LinkedIn job scraping utilities (pure functions, no agentscope dependency).
"""
import ast
import time
import random
import requests
from bs4 import BeautifulSoup

_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_job_description(url: str) -> str:
    """Fetch and extract the job description text from a LinkedIn job page."""
    try:
        time.sleep(random.uniform(1.0, 2.0))
        res = requests.get(url, headers=_HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            desc = soup.find("div", class_="show-more-less-html__markup") or \
                   soup.find("div", class_="description__text")
            if desc:
                text = desc.get_text(separator=" ", strip=True)
                return (text[:1500] + "…") if len(text) > 1500 else text
        return "职位描述不可用（被屏蔽或缺失）"
    except Exception as e:
        return f"获取详情失败: {e}"


def fetch_linkedin_jobs(keywords_list, location: str = "Singapore") -> str:
    """
    Search LinkedIn for jobs matching each keyword.

    Args:
        keywords_list: list of search keywords (or a JSON-encoded list string)
        location: job location filter

    Returns:
        Formatted text with job listings.
    """
    if isinstance(keywords_list, str):
        try:
            keywords_list = ast.literal_eval(keywords_list)
        except Exception:
            keywords_list = [keywords_list]
    if not isinstance(keywords_list, list):
        return "错误: keywords_list 必须是一个字符串列表"

    all_results = []

    for keyword in keywords_list[:3]:
        clean_kw = str(keyword).replace("\n", " ").strip()
        print(f"[LinkedInScraper] Searching: '{clean_kw}'")
        time.sleep(random.uniform(2.0, 4.0))

        params = {
            "keywords": clean_kw,
            "location": location,
            "f_TPR":    "r2592000",
            "pageNum":  0,
        }
        try:
            resp = requests.get(_SEARCH_URL, params=params,
                                headers=_HEADERS, timeout=15)
            if resp.status_code != 200:
                all_results.append(
                    f"'{clean_kw}' 搜索失败 (HTTP {resp.status_code})"
                )
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("li")
            if not cards:
                all_results.append(f"'{clean_kw}' 未找到职位")
                continue

            results = []
            for card in cards[:3]:
                title_el   = card.find("h3", class_="base-search-card__title")
                company_el = card.find("h4", class_="base-search-card__subtitle")
                link_el    = card.find("a",  class_="base-card__full-link")
                if not link_el:
                    continue
                link        = link_el["href"].split("?")[0].strip().rstrip("\n- ")
                description = get_job_description(link)
                title       = title_el.text.strip()   if title_el   else "未知职位"
                company     = company_el.text.strip()  if company_el else "未知公司"
                results.append(
                    f"### {title} @ {company}\n"
                    f"链接: {link}\n"
                    f"要求: {description}\n"
                )

            if results:
                all_results.append(
                    f"--- '{clean_kw}' 的搜索结果 ---\n" + "\n".join(results)
                )
        except Exception as e:
            all_results.append(f"'{clean_kw}' 搜索出错: {e}")

    return "\n\n".join(all_results) if all_results else "未找到任何职位结果"
