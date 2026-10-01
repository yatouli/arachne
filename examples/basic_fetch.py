"""Quick start: fetch, select, adaptive-relocate, and render Markdown."""

from arachne import Fetcher
from arachne.parsing import ElementFingerprint

URL = "https://example.com"

page = Fetcher.fetch(URL, impersonate="chrome124")
print(f"status={page.status_code}  bytes={len(page.content)}  took={page.duration:.2f}s")

# Basic selection
title = page.css("h1::text").get()
print("H1:", title)

# Save a fingerprint, so we can re-find the element after a redesign.
h1 = page.css("h1").first
if h1 is not None:
    fingerprint = ElementFingerprint.from_element(h1)
    print("Fingerprint:", fingerprint)

    # Simulate: re-locate it (works on the same page here, but survives drift).
    relocated = page.selector
    from arachne.parsing import relocate

    matches = relocate(relocated, fingerprint, threshold=0.4)
    print("Relocated H1:", matches.first.text() if matches.first else None)

# Clean, LLM-ready Markdown
print("\n--- markdown ---")
print(page.markdown()[:500])
