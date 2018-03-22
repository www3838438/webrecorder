from webrecorder.models.base import RedisUniqueComponent
import json


# ============================================================================
class Auto(RedisUniqueComponent):
    MY_TYPE = 'auto'

    INFO_KEY = 'a:{auto}:info'
    BR_KEY = 'a:{auto}:br'
    TAB_KEY = 'a:{auto}:t:{reqid}'
    Q_KEY = 'a:{auto}:q'
    SCOPE_KEY = 'a:{auto}:scope'

    ALL_KEYS = 'a:{auto}:*'

    COUNTER_KEY = 'n:autos:count'

    NEW_AUTO_KEY = 'q:auto:add'
    DEL_AUTO_KEY = 'q:auto:del'


    DEFAULT_HOPS = 0
    DEFAULT_BROWSERS = 1

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

        self.data = {'max_browsers': props.get('max_browsers', self.DEFAULT_BROWSERS),
                     'hops': props.get('hops', 0),
                     'num_tabs': props.get('num_tabs', 1)
                    }

        self.data.update({
                     'status': self.INACTIVE,

                     'owner': collection.my_id,
                     'user': collection.get_owner().name,
                     'coll_name': collection.name,
                     'rec': '',

                     'browser': 'chrome:60',
                     'request_ts': '',
                     'type': 'record'
                    })

        scopes = props.get('scopes')
        if scopes:
            scope_key = self.SCOPE_KEY.format(auto=aid)
            for scope in scopes:
                self.redis.sadd(scope_key, scope)

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
        self['status'] = self.READY

    def queue_list(self, list_id):
        if self['status'] not in (self.INACTIVE, self.RUNNING):
            return 'Auto Not Valid'

        collection = self.get_owner()
        if not collection:
            return 'Collection Not Found'

        blist = collection.get_list(list_id)
        if not blist:
            return 'List Not Found'

        rec = self['rec']
        if rec:
            recording = collection.get_recording_by_id(rec, '')
            if not recording.is_open():
                self['status'] = self.DONE
                return 'Recording Finished'

        hops = int(self.get_prop('hops', self.DEFAULT_HOPS))

        for bookmark in blist.get_bookmarks():
            url_req = {'url': bookmark['url']}
            if hops:
                url_req['hops'] = hops
            print('Queuing: ' + str(url_req))
            self.redis.rpush(self.browser_q, json.dumps(url_req))

        return None

    def get_tab_key(self, reqid):
        return self.TAB_KEY.format(auto=self.my_id, reqid=reqid)

    def serialize(self):
        data = super(Auto, self).serialize()
        reqids = self.redis.smembers(self.BR_KEY.format(auto=self.my_id))
        browsers = {}
        for reqid in reqids:
            tabs = self.redis.hgetall(self.get_tab_key(reqid))
            if tabs:
                browsers[reqid] = tabs

        data['active_browsers'] = browsers
        data['queue'] = self.redis.lrange(self.Q_KEY.format(auto=self.my_id), 0, -1)
        data['scopes'] = list(self.redis.smembers(self.SCOPE_KEY.format(auto=self.my_id)))
        return data

    def delete_me(self):
        self.access.assert_can_admin_coll(self.get_owner())

        if not self.delete_object():
            return False

        self.redis.rpush(self.DEL_AUTO_KEY, self.my_id)

