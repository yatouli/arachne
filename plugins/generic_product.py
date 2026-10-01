"""Example site plugin: a generic e-commerce product-listing scraper.

This one uses a declarative :class:`Schema` instead of imperative code — the
schema doubles as documentation and can be serialized/reloaded.
"""

from arachne.parsing import Field, Schema
from arachne.plugins import SitePlugin, plugin


@plugin
class GenericProductPlugin(SitePlugin):
    name = "generic_products"
    # Match any *.myshop.example / shop.example domain and adjust in real use.
    domains = ["books.toscrape.com", "demo.shop.local"]
    url_patterns = [r"/catalogue/", r"/products"]
    description = "Product cards from a generic store (title/price/link/image)"
    fetcher = "http"

    schema = Schema(
        container=".product, .product_pod, .product-card, [data-test='product']",
        fields=[
            Field(name="title", selector="h3::text, .title::text, .product-title::text"),
            Field(name="price", selector=".price_color::text, .price::text, [itemprop='price']::attr(content)"),
            Field(name="url", selector="a::attr(href), h3 a::attr(href)"),
            Field(name="image", selector="img::attr(src)"),
        ],
    )

    def parse(self, page):
        return self.schema.extract(page)
