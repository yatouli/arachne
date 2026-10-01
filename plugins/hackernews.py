"""Example site plugin: Hacker News front page.

Demonstrates the three things every plugin does: declare its target domain,
say how to fetch it, and turn the page into structured records.
"""

from arachne.plugins import SitePlugin, plugin


@plugin
class HackerNewsPlugin(SitePlugin):
    name = "hackernews"
    domains = ["news.ycombinator.com"]
    description = "Front-page stories from Hacker News"
    fetcher = "http"

    def parse(self, page):
        rows = page.css("tr.athing")
        return rows.as_dicts(
            title=".titleline a::text",   # HN switched to .titleline in 2022
            url=".titleline a::attr(href)",
            rank=".rank::text",
            score="~ .score::text",       # sibling selector for the score
            age="~ .age::text",
        )
