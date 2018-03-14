from webrecorder.models.base import RedisUniqueComponent
import json


# ============================================================================
class Auto(RedisUniqueComponent):
    MY_TYPE = 'auto'

    INFO_KEY = 'a:{auto}:info'
    BR_KEY = 'a:{auto}:br'
    Q_KEY = 'a:{auto}:q'

    ALL_KEYS = 'a:{auto}:*'

    COUNTER_KEY = 'n:autos:count'

    NEW_AUTO_KEY = 'q:auto:add'
    DEL_AUTO_KEY = 'q:auto:del'

    ALL_BROWSERS = 'n:auto_br'

    INACTIVE = '0'
    READY = '10'
    RUNNING = '20'
    PAUSED = '30'
    DONE = '40'

    def __init__(self, **kwargs):
        super(Auto, self).__init__(**kwargs)
        self.browser_q = self.Q_KEY.format(auto=self.my_id)

    def init_new(self, collection, props=None):
        self.owner = collection

        aid = self._create_new_id()

        self.data = {'max_browsers': '2',
                     'status': self.INACTIVE,

                     'owner': collection.my_id,
                     'user': collection.get_owner().name,
                     'coll_name': collection.name,
                     'rec': ''

                     'browser': 'chrome:60',
                     'request_ts': '',
                     'type': 'record'
                    }

        self.name = str(aid)
        self._init_new()

        self.redis.rpush(self.NEW_AUTO_KEY, aid)

        return aid

    def start(self):
        if self['status'] != self.INACTIVE:
            return

        collection = self.get_owner()

        recording = collection.create_recording(rec_type='auto')

        self['rec'] = recording.my_id
        self['status'] = self.RUNNING

    def queue_list(self, list_id):
        if self['status'] not in (self.INACTIVE, self.RUNNING):
            return 'Auto Not Valid'

        collection = self.get_owner()
        if not collection:
            return 'Collection Not Found'

        blist = collection.get_list(list_id)
        if not blist:
            return 'List Not Found'

        for bookmark in blist.get_bookmarks():
            url_req = {'url': bookmark['url']}
            logging.debug('Queuing: ' + str(url_req))
            self.redis.rpush(self.browser_q, json.dumps(url_req))

        return None

    def delete_me(self):
        self.access.assert_can_admin_coll(self.get_owner())

        if not self.delete_object():
            return False

        self.redis.rpush(self.DEL_AUTO_KEY, self.my_id)

