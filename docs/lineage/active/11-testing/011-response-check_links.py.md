

```python
"""Link checking utility for gh-link-auditor.

Extracts and validates HTTP/HTTPS URLs from files, reporting status
via structured logging. See LLD #11 for design rationale.
"""

import http.client
import re
import ssl
import time
import urllib.error
import urllib.request

from src.logging_config import setup_logging

# LLD §2.5 step 3.2: Module-level logger
logger = setup_logging("check_links")


def find_urls(filepath: str) -> list[str]:
    """Extracts all HTTP/HTTPS URLs from a file."""
    logger.info("Locating URLs in %s", filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error("Could not read file: %s", e)
        return []

    # Regex to find URLs, including those in markdown parens
    # It avoids matching the final parenthesis if it's part of the markdown
    url_regex = re.compile(r"https?://[a-zA-Z0-9./?_&%=\-~:#]+")

    urls = url_regex.findall(content)
    unique_urls = sorted(list(set(urls)))
    logger.info("Found %d unique URLs.", len(unique_urls))
    return unique_urls


def check_url(url: str, retries: int = 2) -> str:
    """
    Checks a single URL. Returns a status string.
    Uses a standard User-Agent to avoid 403 Forbidden errors.
    """
    # Create a default SSL context that does not verify certs
    # This helps avoid SSL certificate verification errors, which are common
    # but don't necessarily mean the link is "broken" for our purposes.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/58.0.3029.110 Safari/537.36"
        )
    }

    req = urllib.request.Request(url, headers=headers, method="HEAD")

    for attempt in range(retries):
        try:
            # Set a 10-second timeout
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                return f"[  OK  ] (Code: {response.status}) - {url}"
        except urllib.error.HTTPError as e:
            # Server responded, but with an error code (404, 403, 500, etc.)
            return f"[ ERROR ] (Code: {e.code}) - {url}"
        except urllib.error.URLError as e:
            # URL-related error (e.g., DNS failure, timeout)
            if "timed out" in str(e.reason):
                if attempt < retries - 1:
                    time.sleep(1)  # Wait before retry
                    continue  # Try again
                return f"[ TIMEOUT ] - {url}"
            return f"[ FAILED ] (Reason: {e.reason}) - {url}"
        except (http.client.RemoteDisconnected, ConnectionResetError):
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return f"[ DISCONNECTED ] - {url}"
        except Exception as e:
            # Catch-all for other issues (e.g., invalid URL format)
            return f"[ INVALID ] (Error: {type(e).__name__}) - {url}"

    return f"[ FAILED ] (All retries) - {url}"


def main():
    """Main function to check all URLs in README.md."""
    filepath = "README.md"
    urls_to_check = find_urls(filepath)

    if not urls_to_check:
        logger.info("No URLs found to check.")
        return

    logger.info("Starting URL Validation")

    error_count = 0
    for url in urls_to_check:
        status = check_url(url)
        if "ERROR" in status or "FAILED" in status or "TIMEOUT" in status or "INVALID" in status:
            logger.warning(status)
            error_count += 1
        else:
            logger.info(status)

    logger.info("Validation Complete")
    if error_count == 0:
        logger.info("All links are valid.")
    else:
        logger.warning("Found %d potential issues.", error_count)


if __name__ == "__main__":
    main()
```
