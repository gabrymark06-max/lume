"""Verifica isolamento tra browser, accesso e superficie cloud senza rete."""
import os
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import cloud


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LUME_ACCESS_KEY': 'test-secret-with-entropy', 'LUME_CLOUD_DEV': '1'})
        self.env.start()
        self.client = TestClient(cloud.app, base_url='https://lume.test')
        self.headers = {'Origin': 'https://lume.test'}

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def login(self):
        return self.client.post('/api/session',json={'code':'test-secret-with-entropy'},headers=self.headers)

    def rpc(self, path, state=None, data=None, method='GET'):
        return self.client.post('/api/cloud',json={'path':path,'state':state or {},'data':data or {},'method':method},headers=self.headers)

    def test_unauthenticated_cannot_read_or_proxy(self):
        self.assertEqual(self.rpc('/api/state').status_code,401)
        self.assertEqual(self.client.get('/api/media?url=https://example.com').status_code,401)

    def test_cookie_is_private_and_signed(self):
        result=self.login()
        self.assertEqual(result.status_code,200)
        self.assertIn('HttpOnly',result.headers['set-cookie'])
        self.assertIn('Secure',result.headers['set-cookie'])
        self.assertFalse(cloud.valid_session(str(int(time.time()+100))+'.fake'))
        self.assertFalse(cloud.valid_session('broken'))

    def test_rejects_other_origin_and_missing_configuration(self):
        self.assertEqual(self.client.post('/api/session',json={'code':'x'},headers={'Origin':'https://evil.test'}).status_code,403)
        with patch.dict(os.environ,{'LUME_ACCESS_KEY':''}):
            self.assertEqual(self.client.get('/api/session').status_code,503)

    def test_state_isolated_and_engine_restored(self):
        self.login()
        previous=cloud.engine.STATE
        a=self.rpc('/api/state',{'favorites':[{'title':'Browser A','url':'https://example.com/a'}]}).json()
        b=self.rpc('/api/state',{}).json()
        self.assertEqual(a['result']['favorites'][0]['title'],'Browser A')
        self.assertEqual(b['result']['favorites'],[])
        self.assertIs(cloud.engine.STATE,previous)

    def test_no_native_operations_or_arbitrary_routes(self):
        self.login()
        for path in ('/api/mpv','/api/library/pick','/index.html','https://evil.test/api/state'):
            self.assertEqual(self.rpc(path,data={},method='POST').status_code,404)
        self.assertEqual(self.rpc('/api/downloads',data={},method='POST').status_code,422)
        self.assertEqual(self.rpc('/api/library',{'library_paths':['/etc']}).json()['result']['items'],[])

    def test_settings_roundtrip(self):
        self.login()
        a=self.rpc('/api/settings',data={'poster_size':'large'},method='POST').json()
        self.assertEqual(a['result']['settings']['poster_size'],'large')
        b=self.rpc('/api/settings',state=a['state']).json()
        self.assertEqual(b['result']['settings']['poster_size'],'large')
        self.assertEqual(self.rpc('/api/state',{'channels':[{}]}).status_code,422)

if __name__=='__main__':
    unittest.main()
