import scrapy
from scrapy_splash import SplashRequest 
from crawler.items import ChatbotItem
from crawler.utils import parse_json, parse_csv
import os
import pandas as pd
import argparse
parser = argparse.ArgumentParser()
working_dir = os.environ['dir']
database_dir = f"{working_dir}/data/database"



lua_script = """
        function main(splash)
            local num_scrolls = 20
            local scroll_delay = 1.0

            local scroll_to = splash:jsfunc("window.scrollTo")
            local get_body_height = splash:jsfunc(
                "function() {return document.body.scrollHeight;}"
            )
            local url = splash.args.url
            assert(splash:go(url))
            splash:wait(splash.args.wait)

            for _ = 1, num_scrolls do
                scroll_to(0, get_body_height())
                splash:wait(scroll_delay)
            end        
            return {
                html = splash:html(),
                url = splash:url()
                }
                
        end



        """

class TestSpider(scrapy.Spider):
    name = 'test'
    def start_requests(self):
        urls = [url.strip() for url in open(f"{database_dir}/test/urls.txt", 'r').readlines()]
        for url in urls:
            yield SplashRequest(
                url, 
                callback=self.parse_article, 
                args={'wait': 2, 'lua_source': lua_script}
                )
    def parse_article(self, response):
        content = ' '.join([i if ('class' and '/r' and 'id' not in i) else '' for i in response.css("p").getall()][:-2])
        item = ChatbotItem()
        item['content'] = content
        yield item
        
    def parse(self, response):
        urls = []
        responses = response.css('.knswli-title')
        if len(responses) > 0:
            
            for r in responses:
                temp_item = {}
                url = r.css('a::attr(href)').get()
                temp_item['title_raw'] = url
                temp_item['url'] = "https://kenh14.vn/" + url

                urls.append(temp_item)

            # keep passing the metadata and used parser to next request
        df = pd.DataFrame.from_dict(dict([(k, [None]) for k in temp_item.keys()]))

        
        while len(df) != len(urls):  
            
            self.logger.info("NOT FINISHED YET")          
            for item in urls:
                if item['title_raw'] not in df['title_raw']:

                    yield SplashRequest(
                        item['url'], 
                        callback=self.parse_article, 
                        endpoint='execute', 
                        args={'wait': 0.5, 'lua_source': lua_script, 'meta': item} 
                        )
            df = pd.read_csv(test_path)
        # #trace
        # while len(pd.read_csv(test_path)) != len(urls):
        #     print("?????")
        #     self.logger.info("NOT FINISHED YET")
        #     df = pd.read_csv(test_path)
        #     for item in urls:
        #         if item['title_raw'] not in df['title_raw']:
        #             yield SplashRequest(
        #                 item['url'], 
        #                 callback=self.parse_article, 
        #                 endpoint='execute', 
        #                 args={'wait': 0.5, 'lua_source': lua_script, 'meta': item})
        # print("FINISHED ?")