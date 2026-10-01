"""Spider demo: concurrent crawling with auto-throttle and pause/resume-free stats."""

from arachne.spider import CrawlSpider, LinkExtractor, Request, Rule, Spider


class QuotesSpider(Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/"]
    custom_settings = {"concurrency": 4, "auto_throttle": True}

    async def parse(self, response):
        for quote in response.css(".quote"):
            yield {
                "text": quote.css(".text::text").get(),
                "author": quote.css(".author::text").get(),
                "tags": quote.css(".tag::text").getall(),
            }
        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)


class SiteCrawler(CrawlSpider):
    name = "site_crawler"
    start_urls = ["https://example.com"]
    rules = [
        Rule(
            LinkExtractor(deny=[r"\.(jpg|png|gif|css|js)$"], restrict_domains=["example.com"]),
            follow=True,
        )
    ]

    async def parse_item(self, response):
        yield {"url": response.url, "title": response.css("title::text").get()}


if __name__ == "__main__":
    result = QuotesSpider().run()
    print(f"scraped {result.stats.items} items in {result.stats.duration:.2f}s")
    print(result.to_json()[:800])
