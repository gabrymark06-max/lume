import json
import unittest
from urllib.parse import parse_qs,urlsplit
from catalog_features import CatalogFeatures, enrich_cards, payload_records


class CatalogFeatureTests(unittest.TestCase):
    def context(self, payload):
        self.urls=[]
        def fetch(url,**kwargs):
            self.urls.append(url)
            return json.dumps(payload),url,'application/json'
        return {'fetch':fetch,'normalize':lambda x:x.casefold(),'hydration':lambda x:x,
                'state':lambda:{'channels':[{'id':'sc','name':'Canale','url':'https://streaming-community.example/','status':'ready'}]},
                'channel_mode':lambda c:'next'}

    def test_archive_uses_observed_filter_protocol_and_preserves_pagination(self):
        c=CatalogFeatures(self.context({'items':[{'id':42,'slug':'matrix','title':'Matrix','kind':'movie','year':1999,'rating':8.2}], 'count':90}))
        result=c.archive(c.primary(),2,query='Matrix',kind='movie',genre='azione',platform='netflix',year='1999',sort='rating')
        args=parse_qs(urlsplit(self.urls[0]).query)
        self.assertEqual(args['q'],['Matrix'])
        self.assertEqual(args['tipo'],['Film'])
        self.assertEqual(args['genere'],['Azione'])
        self.assertEqual(args['servizio'],['Netflix'])
        self.assertEqual(args['offset'],['30'])
        self.assertEqual(args['sort'],['Valutazione'])
        self.assertEqual(result['next_page'],3)
        self.assertTrue(result['items'][0]['url'].endswith('/titles/42-matrix-streaming'))

    def test_last_archive_page_does_not_offer_nonexistent_page(self):
        c=CatalogFeatures(self.context({'items':[],'count':30}))
        self.assertIsNone(c.archive(c.primary(),2)['next_page'])

    def test_editorial_categories_keep_real_criteria(self):
        c=CatalogFeatures(self.context({'items':[],'count':0}))
        c.discover({'kind':'movie','genre':'christmas'})
        main=[u for u in self.urls if parse_qs(urlsplit(u).query).get('limit')==['30']][-1]
        self.assertEqual(parse_qs(urlsplit(main).query)['q'],['Natale'])
        c.discover({'kind':'movie','genre':'disney'})
        main=[u for u in self.urls if parse_qs(urlsplit(u).query).get('limit')==['30']][-1]
        self.assertEqual(parse_qs(urlsplit(main).query)['servizio'],['Disney+'])
        self.assertEqual(len(c.categories([])),25)

    def test_captured_metadata_is_enriched_without_evaluating_script(self):
        record={'id':42,'legacyId':42,'kind':'movie','title':'Matrix','year':1999,'genres':['Azione'],
                'plot':'Trama della fonte','rating':8.2,'posterUrl':'https://img.example/p.jpg',
                'backdropUrl':'https://img.example/b.jpg','logoUrl':'https://img.example/title.png',
                'imdbId':'tt0133093','scTrailer':True,'networks':['Netflix']}
        data='1:'+json.dumps(record)
        self.assertEqual(len(payload_records(data,lambda x:x)),1)
        result=enrich_cards([{'url':'https://canale.example/titles/42-matrix-streaming'}],data,lambda x:x,'https://canale.example/')[0]
        self.assertEqual(result['description'],'Trama della fonte')
        self.assertEqual(result['platforms'],['Netflix'])
        self.assertIn('content=trailer',result['trailer']['url'])
        self.assertEqual(result['title_image'],'https://img.example/title.png')

    def test_calendar_uses_airstamp_instead_of_assuming_local_airtime(self):
        payload=[{'id':1,'name':'Pilota','season':1,'number':1,'airstamp':'2026-11-02T23:00:00+00:00',
                  'airtime':'18:00','airdate':'2026-11-02','_embedded':{'show':{'id':2,'name':'Serie','webChannel':{'name':'Rete'}}}}]
        c=CatalogFeatures(self.context(payload))
        item=c.calendar('2026-11-02')['items'][0]
        self.assertEqual(item['show_id'],2)
        self.assertEqual(item['airstamp'],'2026-11-02T23:00:00+00:00')


if __name__=='__main__':
    unittest.main()
