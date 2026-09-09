import os

import scrapy


class SelectedStandardsSpider(scrapy.Spider):
    name = 'selected-standards'
    custom_settings = {
        'RETRY_ENABLED': True,
        'RETRY_TIMES': 2,
        'HTTPERROR_ALLOW_ALL': False,
    }

    def __init__(self, start_url=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_url = start_url
        self.selected_ids = [value for value in os.getenv('BIS_SELECTED_IDS', '').split(',') if value]

    def start_requests(self):
        if not self.start_url:
            raise ValueError('A configured BIS start URL is required')
        yield scrapy.Request(self.start_url, callback=self.parse, errback=self.errback_httpbin)

    def parse(self, response):
        # This request is only a scoped availability check; IDs are never discovered from the page.
        yield {'source_url': response.url, 'selected_ids': self.selected_ids}

    def errback_httpbin(self, failure):
        self.logger.error('BIS request failed: %s', failure.value)