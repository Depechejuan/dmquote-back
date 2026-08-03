from urllib.parse import quote

DMLIVE_WIKI_PAGE_PREFIX = "https://dmlive.wiki/wiki/"
_PATH_SAFE = "-._~!$&'()*+,;=:@/"
_ANCHOR_SAFE = "-._~!$&'()*+,;=:@"


def build_dmlive_url(title: str, anchor: str | None = None) -> str:
    """Build a canonical DM Live Wiki page URL from its MediaWiki title."""

    normalized_title = " ".join(str(title).strip().split())
    page_title = normalized_title.replace(" ", "_")
    url = f"{DMLIVE_WIKI_PAGE_PREFIX}{quote(page_title, safe=_PATH_SAFE)}"

    if anchor:
        normalized_anchor = " ".join(str(anchor).strip().split())
        if normalized_anchor:
            url += f"#{quote(normalized_anchor, safe=_ANCHOR_SAFE)}"
    return url
