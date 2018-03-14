from gevent import monkey; monkey.patch_all()

import os
import redis
import time
import requests
import logging
import json
import gevent
import websocket

from webrecorder.utils import init_logging

from warcio.timeutils import timestamp_now

from webrecorder.models.auto import Auto
from webrecorder.models.recording import Recording
from webrecorder.models.usermanager import CLIUserManager

from webrecorder.browsermanager import BrowserManager


# ============================================================================
class AutoManager(object):
    def __init__(self):
        self.user_manager = CLIUserManager()

        self.config = self.user_manager.config
        self.redis = self.user_manager.redis

        browser_redis = redis.StrictRedis.from_url(os.environ['REDIS_BROWSER_URL'],
                                                   decode_responses=True)

        self.browser_mgr = BrowserManager(self.config, browser_redis, self.user_manager)

        self.autos = {}
        self.init_autos()

    def init_autos(self):
        logging.debug('AutoManager Start...')
        for auto_key in self.redis.scan_iter(Auto.INFO_KEY.format(auto='*')):
            aid = auto_key.split(':')[1]
            self.init_auto(aid)

    def init_auto(self, aid):
        auto = RunnableAuto(auto_mgr=self,
                            my_id=aid)

        logging.debug('Adding auto for processing: ' + str(aid))

        if auto.my_id not in self.autos:
            self.autos[auto.my_id] = auto

    def run(self):
        while True:
            self.process_adds()
            self.process_dels()

            for n, auto in self.autos.items():
                auto.process()

            time.sleep(10.0)

    def process_adds(self):
        while True:
            aid = self.redis.lpop(Auto.NEW_AUTO_KEY)
            if not aid:
                break

            self.init_auto(aid)

    def process_dels(self):
        while True:
            aid = self.redis.lpop(Auto.DEL_AUTO_KEY)
            if not aid:
                break

            for n, auto in self.autos.items():
                if n == aid:
                    auto.close()
                    self.autos.pop(aid, None)
                    break

    @classmethod
    def main(cls):
        init_logging(debug=True)

        auto_mgr = AutoManager()
        auto_mgr.run()


# ============================================================================
class RunnableAuto(Auto):
    def __init__(self, **kwargs):
        self.auto_mgr = kwargs['auto_mgr']
        kwargs['redis'] = self.auto_mgr.user_manager.redis
        kwargs['access'] = self.auto_mgr.user_manager.access

        super(RunnableAuto, self).__init__(**kwargs)

        self.browsers = []
        self.cdata = {}
        self.br_key = self.BR_KEY.format(auto=self.my_id)

        if self['status'] != self.RUNNING and self['status'] != self.READY:
            logging.debug('Automation {0} not ready or running'.format(self.my_id))
            return

        self.init_browsers()

    def close(self):
        for browser in self.browsers:
            browser.close()

    def make_new_browser(self, reqid=None):
        browser = AutoBrowser(auto=self, reqid=reqid,
                              cdata=self.cdata)

        self.browsers.append(browser)
        return browser

    def init_browsers(self):
        self.load()

        self.cdata = {'user': self['user'],
                      'coll': self['owner'],
                      'rec': self['rec'],

                      'browser': self['browser'],
                      'browser_can_write': '1',
                      'type': self['type'],
                      'request_ts': self['request_ts'],
                      'url': 'about:blank',
                     }

        self.browsers = []
        active_reqids = self.redis.smembers(self.br_key)

        max_browsers = int(self['max_browsers'])

        self['status'] = self.RUNNING

        for reqid, count in zip(active_reqids, range(max_browsers)):
            if not self.make_new_browser(reqid):
                return

        while len(self.browsers) < max_browsers:
            if not self.make_new_browser():
                return

    def process(self):
        if self['status'] == self.READY:
            self.init_browsers()

        if self['status'] != self.RUNNING:
            return

        logging.debug('Auto Running: ' + self.my_id)

        max_browsers = int(self['max_browsers'])

        while len(self.browsers) > max_browsers:
            browser = self.browsers.pop()
            browser.close()

        while len(self.browsers) < max_browsers:
            if not self.make_new_browser():
                return

        for browser in self.browsers:
            if not browser.running:
                browser.reinit()

    def browser_added(self, reqid):
        self.redis.sadd(self.br_key, reqid)

    def browser_removed(self, reqid):
        if reqid:
            self.redis.srem(self.br_key, reqid)

    def __getitem__(self, name):
        return self.get_prop(name, force_update=True)


# ============================================================================
class AutoBrowser(object):
    CDP_JSON = 'http://{ip}:9222/json'

    REQ_KEY = 'req:{id}'

    WAIT_TIME = 0.5

    def __init__(self, auto, cdata, reqid=None):
        self.auto = auto
        self.redis = auto.auto_mgr.redis
        self.browser_q = auto.browser_q
        self.browser_mgr = auto.auto_mgr.browser_mgr
        self.cdata = cdata

        self.running = False

        #self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)

        self.init_with_reqid(reqid)

        logging.debug('Auto Browser Inited: ' + self.reqid)

    def reinit(self):
        if self.running:
            return

        self.init_with_reqid()

        logging.debug('Auto Browser Re-Inited: ' + self.reqid)

    def init_with_reqid(self, reqid=None):
        ip = None
        tab = None

        # attempt to connect to existing browser/tab
        if reqid:
            ip = self.browser_mgr.get_ip_for_reqid(reqid)
            if ip:
                tab = self.find_browser_tab(ip)

            # ensure reqid is removed
            if not tab:
                self.auto.browser_removed(reqid)

        # no tab found, init new browser
        if not tab:
            reqid, ip, tab = self.init_new_browser()

        self.reqid = reqid
        self.ip = ip
        self.tab = tab

        self.auto.browser_added(reqid)

        self.init_tab_conn()
        gevent.spawn(self.recv_loop)

    def find_browser_tab(self, ip, url=None):
        try:
            res = requests.get(self.CDP_JSON.format(ip=ip))
            tabs = res.json()
        except:
            return

        for tab in tabs:
            if tab['type'] == 'page' and (not url or url == tab['url']):
                return tab

        return None

    def init_new_browser(self):
        launch_res = self.browser_mgr.request_new_browser(self.cdata)
        reqid = launch_res['reqid']

        # wait for browser init
        while True:
            res = requests.get('http://shepherd:9020/init_browser?reqid={0}'.format(reqid))

            try:
                res = res.json()
            except Exception as e:
                logging.debug('Browser Init Failed: ' + str(e))
                return False

            if 'cmd_host' in res:
                break

            #if reqid not in self.req_cache:
            #    logging.debug('Waited too long, cancel browser launch')
            #    return False

            logging.debug('Waiting for Browser: ' + str(res))
            time.sleep(self.WAIT_TIME)

        logging.debug('Launched: ' + str(res))

        # wait to find tab
        while True:
            tab = self.find_browser_tab(res['ip'])
            if tab:
                break

            time.sleep(self.WAIT_TIME)
            logging.debug('Waiting for Tab')

        return reqid, res['ip'], tab

    def init_tab_conn(self):
        try:
            self.tab_ws = websocket.create_connection(self.tab['webSocketDebuggerUrl'])

            self.id_count = 0
            self.frame_id = ''
            self.curr_mime = ''

            self.send_ws({"method": "Page.enable"})
            logging.debug('Page.enable on ' + self.tab['webSocketDebuggerUrl'])

            self.running = True

            # quene next url!
            self.queue_next()

        except Exception as e:
            logging.debug(str(e))
            self.running = False

    def queue_next(self):
        def wait_queue():
            name, url_req_data = self.redis.blpop(self.browser_q)
            url_req = json.loads(url_req_data)

            self.curr_url_req = url_req

            try:
                logging.debug('Queuing Next: ' + str(url_req))
                self.send_ws({"method": "Page.navigate", "params": {"url": url_req['url']}})
            except:
                self.redis.rpush(self.browser_q, url_req_data)

        gevent.spawn(wait_queue)

    def recv_loop(self):
        try:
            while self.running:
                resp = self.tab_ws.recv()
                resp = json.loads(resp)

                try:
                    if resp.get('id') == self.id_count and 'result' in resp:
                        self.handle_result(resp)

                    elif resp.get('method') == 'Page.frameNavigated':
                        self.handle_frameNavigated(resp)

                    elif resp.get('method') == 'Page.frameStoppedLoading':
                        self.handle_frameStoppedLoading(resp)
                except Exception as re:
                    logging.warn('*** Error handling response')
                    logging.warn(str(re))

                logging.debug(str(resp))
        except Exception as e:
            logging.warn(str(e))

        finally:
            self.close()

    def handle_result(self, resp):
        result = resp['result']
        frame_id = result.get('frameId')
        if frame_id:
            self.frame_id = frame_id

    def handle_frameStoppedLoading(self, resp):
        frame_id = resp['params']['frameId']

        # ensure top-frame stopped loading
        if frame_id != self.frame_id:
            return

        self.queue_next()

    def handle_frameNavigated(self, resp):
        frame = resp['params']['frame']

        # ensure target frame
        if frame['id'] != self.frame_id:
            return

        # if not top frame, skip
        if frame.get('parentId'):
            return

        self.curr_mime = frame['mimeType']

        # if text/html, already should have been added
        if self.curr_mime != 'text/html':
            recording = Recording(my_id=self.cdata['rec'],
                                  redis=self.redis,
                                  access=self.auto.auto_mgr.user_manager.access)

            page = {'url': frame['url'],
                    'title': frame['url'],
                    'timestamp': self.cdata['request_ts'] or timestamp_now(),
                    'browser': self.cdata['browser'],
                   }

            recording.add_page(page, False)

    def send_ws(self, data):
        self.id_count += 1
        data['id'] = self.id_count
        self.tab_ws.send(json.dumps(data))

    def close(self):
        self.running = False
        self.auto.browser_removed(self.reqid)
        self.reqid = None

        try:
            if self.tab_ws:
                self.tab_ws.close()
        except:
            pass

        finally:
            self.tab_ws = None


# ============================================================================
if __name__ == "__main__":
    AutoManager.main()
