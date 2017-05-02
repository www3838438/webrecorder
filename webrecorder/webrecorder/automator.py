from gevent import monkey; monkey.patch_all()

from webrecorder.redisman import init_manager_for_cli
from webrecorder.utils import load_wr_config
from webrecorder.contentcontroller import ContentController
from webrecorder.browsermanager import BrowserManager

from warcio.timeutils import timestamp_now

from pywb.utils.canonicalize import canonicalize

import os
import redis
import time
import requests
import logging
import json
import gevent


# ============================================================================
class Automator(object):
    def __init__(self):
        config = load_wr_config()

        # Init Redis
        self.app_redis = redis.StrictRedis.from_url(os.environ['REDIS_BASE_URL'],
                                                    decode_responses=True)

        self.redis = redis.StrictRedis.from_url(os.environ['REDIS_BROWSER_URL'],
                                                decode_responses=True)

        # Init Content Loader/Rewriter
        content_app = ContentController(app=None,
                                        jinja_env=None,
                                        config=config,
                                        redis=self.redis)

        self.content_app = content_app

        # Init Browser Mgr
        self.browser_mgr = BrowserManager(config, self.redis, content_app)

        self.manager = init_manager_for_cli(config=config,
                                            browser_mgr=self.browser_mgr,
                                            browser_redis=self.redis,
                                            content_app = content_app)

        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        self.pubsub.psubscribe('from_cbr_ps:*')

        logging.debug('Automator inited')

        self.req_cache = {}

        self.auto_key = 'r:{user}:{coll}:{rec}:auto'
        self.auto_br_key = 'r:{user}:{coll}:{rec}:auto:br'
        self.q_key = 'c:{user}:{coll}:{rec}:q'
        self.qp_key = 'c:{user}:{coll}:{rec}:qp'
        self.qn_key = 'c:{user}:{coll}:{rec}:qn'
        self.REQ_TIME = 120
        self.NUM_BROWSERS = 1

        self.START_URL = 'http://webrecorder.io/_standby'

    def loop_msg(self):
        #for item in self.pubsub.listen():
        while True:
            item = self.pubsub.get_message()
            if not item:
                continue

            self.process_msg(item['channel'], json.loads(item['data']))

    def process_msg(self, channel, msg):
        reqid = channel.split(':', 1)[1]
        res = self.req_cache.get(reqid)
        if not res:
            logging.debug('Invalid Req: ' + reqid)
            return

        user, coll, rec = res

        if msg['ws_type'] == 'remote_url':
            logging.debug(str(channel) + ': ' + str(msg))

            if self.should_extract_links(user, coll, rec, msg['page']):
                self.send_response(reqid, {'ws_type': 'extract-req'})
            else:
                logging.debug('Loading next on {0}'.format(reqid))
                #self.check_done(user, coll, rec, msg['url'])
                gevent.spawn(self.load_next_url, user, coll, rec, reqid)

            self.redis.expire('req_ttl:' + reqid, self.REQ_TIME)

        elif msg['ws_type'] == 'extract-resp':
            if msg['phase'] == 'start':
                logging.debug(str(channel) + ': ' + str(msg))
                self.redis.expire('req_ttl:' + reqid, self.REQ_TIME)
            elif msg['phase'] == 'url':
                self.queue_new_url(user, coll, rec, msg['url'])

            elif msg['phase'] == 'end':
                logging.debug(str(channel) + ': ' + str(msg))
                self.check_done(user, coll, rec, msg['url'])
                gevent.spawn(self.load_next_url, user, coll, rec, reqid)

    def should_extract_links(self, user, coll, rec, page_info):
        auto_key = self.auto_key.format(user=user,
                                        coll=coll,
                                        rec=rec)

        surt_scope = self.redis.hget(auto_key, 'surt_scope')
        surt_scope = surt_scope or ''

        surt = canonicalize(page_info['url'])

        return surt.startswith(surt_scope)

    def queue_new_url(self, user, coll, rec, url):
        existing_ts = self.manager._get_url_ts(user, coll, rec, url)
        if existing_ts:
            logging.debug('Already captured: {0}'.format(url))
            return False

        q_key = self.q_key.format(user=user,
                                  coll=coll,
                                  rec=rec)

        logging.debug('Queued {0} to {1}'.format(url, q_key))
        self.redis.sadd(q_key, url)
        return True

    def check_done(self, user, coll, rec, url):
        if not url:
            return

        qp_key = self.qp_key.format(user=user,
                                    coll=coll,
                                    rec=rec)

        removed = self.redis.srem(qp_key, url)
        if not removed:
            return

        # re-add url if not found!
        return not self.queue_new_url(user, coll, rec, url)

    def load_next_url(self, user, coll, rec, reqid):
        q_key = self.q_key.format(user=user,
                                  coll=coll,
                                  rec=rec)

        qp_key = self.qp_key.format(user=user,
                                    coll=coll,
                                    rec=rec)

        if self._find_next_url(user, coll, rec, reqid, q_key, qp_key):
            return True

        # retry pending again?
        if self._find_next_url(user, coll, rec, reqid, qp_key, qp_key):
            return True

        return False

    def _find_next_url(self, user, coll, rec, reqid, q_key, qp_key):
        while True:
            url = self.redis.spop(q_key)
            if not url:
                logging.debug('No more urls from {0}'.format(q_key))
                return False

            if self._do_load_url(user, coll, rec, url, reqid, qp_key):
                logging.debug('Found pending url {0}'.format(qp_key))
                return True

    def is_queueable_url(self, user, coll, rec, url):
        existing_ts = self.manager._get_url_ts(user, coll, rec, url)
        if existing_ts:
            logging.debug('Skipping, already recorded: ' + url)
            return False

        try:
            res = requests.head(url, allow_redirects=True)
            content_type = res.headers.get('content-type')
            if (content_type and
                'text/html' not in content_type and
                'application/xhtml' not in content_type):

                qn_key = self.qn_key.format(user=user, coll=coll, rec=rec)
                self.redis.sadd(qn_key, url)
                logging.debug('Content Type: {0} - Skipping: {1}'.format(content_type, url))
                return False

        except:
            logging.debug('Skipping, invalid url: ' + url)
            return False

        return True

    def _do_load_url(self, user, coll, rec, url, reqid, qp_key):
        logging.debug('Loading ({0}) Next: {1}'.format(reqid, url))
        self.redis.sadd(qp_key, url)

        self.send_response(reqid, {'ws_type': 'set_url',
                                   'url': url})

        self.redis.setex('req_ttl:' + reqid, self.REQ_TIME, url)
        return True

    def send_response(self, reqid, msg):
        channel = 'to_cbr_ps:' + reqid
        self.redis.publish(channel, json.dumps(msg))

    def create_auto(self, user, coll, rec, browser, url):
        logging.debug('Creating Automation')

        if not self.manager.has_collection(user, coll):
            self.manager.create_collection(user, coll, coll)

        rec_title = rec
        rec = self.content_app.sanitize_title(rec)

        recording = self.manager.create_recording(user, coll, rec, rec_title)

        rec = recording['id']

        auto_key = self.auto_key.format(user=user,
                                        coll=coll,
                                        rec=rec)

        self.redis.hset(auto_key, 'browser', browser)
        self.redis.hset(auto_key, 'surt_scope', canonicalize(url))

        return rec, auto_key

    def launch_browser(self, browser, auto_key, user, coll, rec):
        ts = timestamp_now()
        url = self.START_URL

        params = {'user': user,
                  'coll': coll,
                  'rec': rec,
                  'request_ts': ts,
                  'url': url,
                  'type': 'record',
                  'browser': browser,
                  'browser_can_write': True,
                  'ip': '',
                 }

        self.browser_mgr.fill_upstream_url(params, ts)

        launch_res = self.browser_mgr.request_prepared_browser(browser, params)
        reqid = launch_res['reqid']

        self.redis.hset(auto_key + ':br', reqid, 0)
        self.redis.setex('req_ttl:' + reqid, self.REQ_TIME, url)

        self.req_cache[reqid] = (user, coll, rec)

        while True:
            res = requests.get('http://shepherd:9020/init_browser?reqid={0}'.format(reqid))

            try:
                res = res.json()
            except Exception as e:
                logging.debug('Browser Init Failed: ' + str(e))
                self.remove_browser(auto_key, reqid, False)
                return False

            if 'cmd_host' in res:
                break

            if reqid not in self.req_cache:
                logging.debug('Waited too long, cancel browser launch')
                return False

            logging.debug('Waiting for Browser: ' + str(res))
            time.sleep(3)

        logging.debug('Launched: ' + str(res))

    def auto_loop(self):
        while True:
            for key in self.redis.scan_iter(match='r:*:auto'):
                self.process_auto(key)

                time.sleep(10)

    def process_auto(self, auto_key):
        logging.debug('Processing: ' + auto_key)

        browsers = self.redis.hgetall(auto_key + ':br')

        user, coll, rec = auto_key.split(':')[1:4]

        logging.debug('LEN: ' + str(len(browsers)))

        for reqid in browsers.keys():
            ttl = self.redis.ttl('req_ttl:' + reqid)
            if ttl == -2:
                logging.debug('No Key Removing: ' + reqid)
                gevent.spawn(self.remove_browser, auto_key, reqid, True)

            elif ttl < 60 or (browsers[reqid] == self.START_URL):
                gevent.spawn(self.load_next_url, user, coll, rec, reqid)

        num_to_add = self.NUM_BROWSERS - len(browsers)
        if num_to_add > 0:
            logging.debug('Num To Add: ' + str(num_to_add))
            browser = self.redis.hget(auto_key, 'browser')

            while num_to_add > 0:
                logging.debug('Launching New Browser')
                gevent.spawn(self.launch_browser, browser, auto_key, user, coll, rec)
                #self.launch_browser(browser, auto_key, user, coll, rec)
                num_to_add -= 1

    def remove_browser(self, auto_key, reqid, call_delete=False):
        if call_delete:
            res = requests.delete('http://shepherd:9020/delete_browser/{0}'.format(reqid))

            res = res.json()

            logging.debug('Delete Result: ' + str(res))

            if 'success' in res:
                call_delete = False

        #if not call_delete:
        self.redis.hdel(auto_key + ':br', reqid)
        self.req_cache.pop(reqid, '')

    def cleanup(self):
        res = requests.delete('http://shepherd:9020/delete_all')
        for key in self.redis.keys(self.q_key.format(user='*', coll='*', rec='*')):
            self.redis.delete(key)

        #for key in self.redis.keys(self.auto_key.format(user='*', coll='*', rec='*')):
        #    self.redis.delete(key)

# ============================================================================
def main(debug=True):
    logging.basicConfig(format='%(asctime)s: [%(levelname)s]: %(message)s',
                        level=logging.DEBUG if debug else logging.INFO)

    a = Automator()
    a.cleanup()
    for key in a.redis.keys('c:ilya:test:*'):
        a.redis.delete(key)

    url = 'http://example.com/'

    rec, auto_key = a.create_auto('ilya', 'test', 'auto', 'chrome', url)

    a.queue_new_url('ilya', 'test', rec, url)

    gevent.spawn(a.loop_msg)

    #a.auto_loop()
    while True:
        a.process_auto(auto_key)
        time.sleep(10)

    logging.debug('Done?')


# ============================================================================
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e)
        import traceback
        traceback.print_exc()


