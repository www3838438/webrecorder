import os
import redis
import time
import requests
import logging
import json
import gevent
import websocket

from webrecorder.utils import init_logging

from webrecorder.models.auto import Auto

from webrecorder.browsermanager import BrowserManager
from webrecorder.models.usermanager import CLIUserManager


# ============================================================================
class AutoManager(object):
    def __init__(self):
        self.user_manager = CLIUserManager()

        self.config = self.user_manager.config
        self.redis = self.user_manager.redis

        browser_redis = redis.StrictRedis.from_url(os.environ['REDIS_BROWSER_URL'],
                                                        decode_responses=True)

        self.browser_mgr = BrowserManager(self.config, browser_redis, self.user_manager)

        self.autos = []
        self.init_autos()

    def init_autos(self):
        for auto_key in self.redis.scan_iter(Auto.INFO_KEY.format('*')):
            aid = auto_key.split(':')[1]
            self.init_auto(aid)

    def init_auto(self, aid):
        auto = RunnableAuto(auto_mgr=self,
                            my_id=aid)

        logging.debug('Adding auto for processing: ' + str(aid))

        auto.init_browsers()

        self.autos.append(auto)

    def run(self):
        while True:
            self.process_adds()
            self.process_dels()

            for auto in self.autos:
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

            for auto in self.autos:
                if auto.my_id == aid:
                    self.autos.pop(auto, None)
                    break

    @classmethod
    def main():
        init_logging()

        auto_mgr = AutoManager()
        auto_mgr.run()


# ============================================================================
class RunnableAuto(Auto):
    def __init__(self, **kwargs):
        self.auto_mgr = kwargs['auto_mgr']
        kwargs['redis'] = self.auto_mgr.user_manager.redis
        kwargs['access'] = self.auto_mgr.user_manager.access

        super(RunnableAuto, self).__init__(**kwargs)

        self.cdata = {}
        self.br_key = self.BR_KEY.format(auto=self.my_id)

    def make_new_browser(self, reqid=None):
        browser = AutoBrowser(auto=self, reqid=reqid,
                              cdata=self.shared_data)

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

        if self['status'] != self.RUNNING:
            logging.debug('Automation {0} not running'.format(self.my_id))
            return

        active_reqids = self.redis.smembers(self.br_key)

        max_browsers = int(self['max_browsers'])

        for reqid, count in zip(active_reqids, range(max_browsers)):
            if not self.make_new_browser(reqid):
                return

        while len(self.browsers) < max_browsers:
            if not self.make_new_browser():
                return

    def process(self):
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
        self.redis.srem(self.br_key, reqid)


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

        gevent.spawn(self.recv_loop)

    def reinit(self):
        if self.running:
            return

        self.init_with_reqid()

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
            self.tab_ws = websocket.create_connection(tab['webSocketDebuggerUrl'])

            self.id_count = 1

            self.send_ws({"method": "Page.enable"})
            logging.debug('Page.enable on ' + tab['webSocketDebuggerUrl'])

            self.running = True

            # quene next url!
            self.queue_next()

        except Exception as e:
            logging.debug(str(e))
            self.running = False

    def queue_next(self):
        def wait_queue():
            name, url_req = self.redis.blpop(self.browser_q)
            url_req = json.loads(url_req)

            self.curr_url_req = url_req

            logging.debug('Queuing Next: ' + str(url_req))
            self.send_ws({"method": "Page.navigate", "params": {"url": url_req['url']}})

        gevent.spawn(wait_queue)

    def recv_loop(self):
        try:
            while self.running:
                resp = self.tab_ws.recv()
                resp = json.loads(resp)
                if resp.get('method') == 'Page.frameStoppedLoading':
                    self.queue_next()

                logging.debug(str(resp))
        except Exception as e:
            logging.debug(str(e))

        finally:
            self.close()

    def send_ws(self, data):
        data['id'] = self.id_count
        self.id_count += 1
        self.tab_ws.send(json.dumps(data))

    def close(self):
        self.running = False
        self.auto.browser_removed(self.reqid)


# ============================================================================
if __name__ == "__main__":
    AutoManager.main()
