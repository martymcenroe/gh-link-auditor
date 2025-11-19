import re
import urllib.request
import urllib.error
import http.client
import ssl
import time

def find_urls(filepath: str) -> list[str]:
    """Extracts all HTTP/HTTPS URLs from a file."""
    print(f"--- Locating URLs in {filepath} ---")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"ERROR: Could not read file: {e}")
        return []

    # Regex to find URLs, including those in markdown parens
    # It avoids matching the final parenthesis if it''s part of the markdown
    url_regex = re.compile(r"https?://[a-zA-Z0-9./?_&%=\-~:#]+")
    
    urls = url_regex.findall(content)
    unique_urls = sorted(list(set(urls)))
    print(f"Found {len(unique_urls)} unique URLs.")
    return unique_urls

def check_url(url: str, retries: int = 2) -> str:
    """
    Checks a single URL. Returns a status string.
    Uses a standard User-Agent to avoid 403 Forbidden errors.
    """
    # Create a default SSL context that does not verify certs
    # This helps avoid SSL certificate verification errors, which are common
    # but don''t necessarily mean the link is "broken" for our purposes.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
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
                    time.sleep(1) # Wait before retry
                    continue # Try again
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
        print("No URLs found to check.")
        return

    print("\n--- Starting URL Validation ---")
    
    error_count = 0
    for url in urls_to_check:
        status = check_url(url)
        print(status)
        if "ERROR" in status or "FAILED" in status or "TIMEOUT" in status or "INVALID" in status:
            error_count += 1
            
    print("--- Validation Complete ---")
    if error_count == 0:
        print("All links are valid.")
    else:
        print(f"Found {error_count} potential issues.")

if __name__ == "__main__":
    main()