import requests
import pytest


# ============================================================================
class TestAuto(object):
    PREFIX = 'http://localhost:8089'
    USER = 'testauto'
    LIST_ID = ''
    AUTO_ID = ''

    @classmethod
    def setup_class(cls):
        cls.session = requests.session()

    def get(self, url, **kwargs):
        full_url = self.PREFIX + url
        return self.session.get(full_url, **kwargs)

    def post(self, url, **kwargs):
        full_url = self.PREFIX + url
        return self.session.post(full_url, **kwargs)

    def delete(self, url, **kwargs):
        full_url = self.PREFIX + url
        return self.session.delete(full_url, **kwargs)

    @pytest.mark.always
    def test_login(self):
        params = {'username': self.USER,
                  'password': 'TestTest123',
                 }

        res = self.post('/api/v1/login', json=params)
        assert res.json()['username'] == self.USER

    def test_create_coll(self):
        res = self.post('/api/v1/collections?user=testauto',
                        data={'title': 'Auto Test'})

        assert res.json()['collection']['id'] == 'auto-test'
        assert res.json()['collection']['title'] == 'Auto Test'

    def test_create_list(self):
        params = {'title': 'Seed List',
                  'desc': 'List Description Goes Here!'
                 }

        res = self.post('/api/v1/lists?user=testauto&coll=auto-test', json=params)
        assert res.json()['list']
        assert res.json()['list']['title'] == 'Seed List'

        TestAuto.LIST_ID = res.json()['list']['id']

    def test_add_bookmarks(self):
        bookmarks = [
                     {'url': 'http://rhizome.org/', 'title': 'https://rhizome.org/'},

                     #{'url': 'http://example.com/', 'title': 'Example Com'},
                     #{'url': 'http://iana.org/', 'title': 'IANA'},
                     #{'url': 'https://eff.org/', 'title': 'EFF'},

                     #{'url': 'https://eligrey.com/', 'title': 'XHTML'},
                     #{'url': 'https://twitter.com/webrecorder_io', 'title': 'Twitter'},
                     #{'url': 'https://twitter.com/', 'title': 'Twitter'},

                     #{'url': 'http://unec.edu.az/application/uploads/2014/12/pdf-sample.pdf', 'title': 'A PDF'},
                     #{'url': 'https://www.iana.org/_img/2015.1/iana-logo-homepage.svg', 'title': 'An Image'},
                    ]

        list_id = self.LIST_ID
        res = self.post('/api/v1/list/%s/bulk_bookmarks?user=testauto&coll=auto-test' % list_id,
                        json=bookmarks)

        assert res.json()['list']

    @pytest.mark.append
    def test_append_only(self, append, auto_id):
        params = {'title': 'Add Url'}

        res = self.post('/api/v1/lists?user=testauto&coll=auto-test', json=params)

        list_id = res.json()['list']['id']

        bookmarks = [{'url': append, 'title': append}]
        res = self.post('/api/v1/list/%s/bulk_bookmarks?user=testauto&coll=auto-test' % list_id,
                        json=bookmarks)

        assert res.json()['list']

        params = {'list': list_id}
        res = self.post('/api/v1/auto/{0}/queue_list?user=testauto&coll=auto-test'.format(auto_id), json=params)

        assert res.json()['status']

    def test_create_auto(self):
        params = {'hops': 10,
                  'num_tabs': 3,
                  'max_browsers': 2,
                  'scopes': ['rhizome.org'],
                 }

        res = self.post('/api/v1/auto?user=testauto&coll=auto-test', json=params)

        assert res.json()['auto']
        TestAuto.AUTO_ID = res.json()['auto']

    def test_add_list(self):
        params = {'list': self.LIST_ID}
        res = self.post('/api/v1/auto/{0}/queue_list?user=testauto&coll=auto-test'.format(self.AUTO_ID), json=params)

        assert res.json()['status']

    def test_get_auto(self):
        res = self.get('/api/v1/auto/{0}?user=testauto&coll=auto-test'.format(self.AUTO_ID))

        assert res.json()['auto']
        assert res.json()['auto']['queue']

    @pytest.mark.delete
    def _test_delete_auto(self):
        res = self.delete('/api/v1/auto/{0}?user=testauto&coll=auto-test'.format(self.AUTO_ID))

        assert res.json() == {'deleted_id': str(self.AUTO_ID)}

    @pytest.mark.delete
    def test_delete_coll(self):
        res = self.delete('/api/v1/collections/auto-test?user=testauto')

        assert res.json() == {'deleted_id': 'auto-test'}


