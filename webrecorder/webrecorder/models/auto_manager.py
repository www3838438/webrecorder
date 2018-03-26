from gevent import monkey; monkey.patch_all()

import os
import redis
import time
import requests
import logging
import json
import gevent
import websocket
import traceback

import re
from urllib.parse import quote

from webrecorder.utils import init_logging

from warcio.timeutils import timestamp_now

from webrecorder.models.auto import Auto
from webrecorder.models.recording import Recording
from webrecorder.models.usermanager import CLIUserManager

from webrecorder.browsermanager import BrowserManager


# ============================================================================
class AutoManager(object):
    INDEX_TEMPL = '{warcserver}/replay/index?param.user={user}&param.coll={coll}&param.rec={rec}&allowFuzzy=0'

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

        if auto['status'] == auto.DONE:
            return

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

        self.num_tabs = int(self.get_prop('num_tabs', 1))

        if self['status'] != self.RUNNING and self['status'] != self.READY:
            logging.debug('Automation {0} not ready or running'.format(self.my_id))
            return

        scopes = self.redis.smembers(self.SCOPE_KEY.format(auto=self.my_id))
        self.scopes = [re.compile(scope) for scope in scopes]

        self.recording = self._init_recording()

        self.init_browsers()

    def _init_recording(self):
        recording = Recording(my_id=self['rec'],
                              redis=self.redis,
                              access=self.auto_mgr.user_manager.access)

        return recording

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

        self.index_check_url = AutoManager.INDEX_TEMPL.format(
                                    warcserver=os.environ['WARCSERVER_HOST'],
                                    user=self.cdata['user'],
                                    coll=self.cdata['coll'],
                                    rec=self.cdata['rec'])

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

        if not self.recording.is_open():
            self['status'] = self.DONE
            logging.debug('Recording Finished, Closing Auto')
            self.redis.rpush(Auto.DEL_AUTO_KEY, self.my_id)
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
            self.redis.delete(self.get_tab_key(reqid))

    def tab_added(self, reqid, tabid, url):
        self.redis.hset(self.get_tab_key(reqid), tabid, url)

    def tab_removed(self, reqid, tabid):
        if reqid:
            self.redis.hdel(self.get_tab_key(reqid), tabid)

    def __getitem__(self, name):
        return self.get_prop(name, force_update=True)


# ============================================================================
class AutoBrowser(object):
    CDP_JSON = 'http://{ip}:9222/json'
    CDP_JSON_NEW = 'http://{ip}:9222/json/new'

    REQ_KEY = 'req:{id}'

    WAIT_TIME = 0.5

    def __init__(self, auto, cdata, reqid=None):
        self.auto = auto
        self.redis = auto.auto_mgr.redis
        self.browser_q = auto.browser_q
        self.browser_mgr = auto.auto_mgr.browser_mgr
        self.cdata = cdata

        self.reqid = None

        self.num_tabs = self.auto.num_tabs

        self.pubsub = self.redis.pubsub(ignore_subscribe_messages=True)

        self.running = False

        self.init(reqid)

        gevent.spawn(self.recv_pubsub_loop)

        logging.debug('Auto Browser Inited: ' + self.reqid)

    def reinit(self):
        if self.running:
            return

        self.init()

        logging.debug('Auto Browser Re-Inited: ' + self.reqid)

    def init(self, reqid=None):
        self.tabs = []
        ip = None
        tab_datas = None

        self.close()

        # attempt to connect to existing browser/tab
        if reqid:
            ip = self.browser_mgr.get_ip_for_reqid(reqid)
            if ip:
                tab_datas = self.find_browser_tabs(ip)

            # ensure reqid is removed
            if not tab_datas:
                self.auto.browser_removed(reqid)

        # no tab found, init new browser
        if not tab_datas:
            reqid, ip, tab_datas = self.init_new_browser()

        self.reqid = reqid
        self.ip = ip
        self.tabs = []

        for tab_data in tab_datas:
            tab = AutoTab(self, tab_data)
            self.tabs.append(tab)

        self.running = True

        self.auto.browser_added(reqid)

        self.pubsub.subscribe('from_cbr_ps:' + reqid)

    def find_browser_tabs(self, ip, url=None, require_ws=True):
        try:
            res = requests.get(self.CDP_JSON.format(ip=ip))
            tabs = res.json()
        except:
            return {}

        filtered_tabs = []

        for tab in tabs:
            logging.debug(str(tab))

            if require_ws and 'webSocketDebuggerUrl' not in tab:
                continue

            if tab.get('type') == 'page' and (not url or url == tab['url']):
                filtered_tabs.append(tab)

        return filtered_tabs

    def get_tab_for_url(self, url):
        tabs = self.find_browser_tabs(self.ip, url=url, require_ws=False)
        if not tabs:
            return None

        id_ = tabs[0]['id']
        for tab in self.tabs:
            if tab.tab_id == id_:
                return tab

        return None

    def add_browser_tab(self, ip):
        try:
            res = requests.get(self.CDP_JSON_NEW.format(ip=ip))
            tab = res.json()
        except Exception as e:
            logging.error('*** ' + str(e))

        return tab

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
                return None, None, None

            if 'cmd_host' in res:
                break

            #if reqid not in self.req_cache:
            #    logging.debug('Waited too long, cancel browser launch')
            #    return False

            logging.debug('Waiting for Browser: ' + str(res))
            time.sleep(self.WAIT_TIME)

        logging.debug('Launched: ' + str(res))

        # wait to find first aab
        while True:
            tab_datas = self.find_browser_tabs(res['ip'])
            if tab_datas:
                break

            time.sleep(self.WAIT_TIME)
            logging.debug('Waiting for first tab')

        # add other tabs
        for tab_count in range(self.auto.num_tabs - 1):
            tab_data = self.add_browser_tab(res['ip'])
            tab_datas.append(tab_data)

        return reqid, res['ip'], tab_datas

    def pubsub_listen(self):
        try:
            for item in self.pubsub.listen():
                yield item
        except:
            return

    def recv_pubsub_loop(self):
        logging.debug('Start PubSub Listen')

        for item in self.pubsub_listen():
            try:
                if item['type'] != 'message':
                    continue

                msg = json.loads(item['data'])
                logging.debug(str(msg))

                if msg['ws_type'] == 'remote_url':
                    pass
                    #logging.debug('URL LOADED: ' + str(msg))
                    #logging.debug('AUTOSCROLLING')

                elif msg['ws_type'] == 'autoscroll_resp':
                    tab = self.get_tab_for_url(msg['url'])
                    if tab:
                        logging.debug('TAB FOUND')
                        tab.load_links()
                    else:
                        logging.debug('TAB NOT FOUND!')

            except:
                traceback.print_exc()

    def send_pubsub(self, msg):
        if not self.reqid:
            return

        channel = 'to_cbr_ps:' + self.reqid
        msg = json.dumps(msg)
        self.redis.publish(channel, msg)

    def close(self):
        self.running = False

        if self.pubsub:
            self.pubsub.unsubscribe()

        if self.reqid:
            self.auto.browser_removed(self.reqid)

        for tab in self.tabs:
            tab.close()

        self.reqid = None


# ============================================================================
class AutoTab(object):
    def __init__(self, browser, tab_data):
        self.tab_id = tab_data['id']
        self.browser = browser
        self.redis = browser.redis
        self.auto = browser.auto
        self.browser_q = browser.browser_q

        self.tab_data = tab_data

        self.ws = websocket.create_connection(tab_data['webSocketDebuggerUrl'])

        self.id_count = 0
        self.frame_id = ''
        self.curr_mime = ''
        self.curr_url = ''
        self.hops = 0

        self.callbacks = {}

        self.send_ws({"method": "Page.enable"})
        self.send_ws({"method": "Runtime.enable"})
        logging.debug('Page.enable on ' + tab_data['webSocketDebuggerUrl'])

        #self.send_ws({"method": "Console.enable"})

        gevent.spawn(self.recv_ws_loop)

        # quene next url!
        self.queue_next()

    def queue_next(self):
        gevent.spawn(self.wait_queue)

    def already_recorded(self, url):
        url = self.auto.index_check_url + '&url=' + quote(url)
        try:
            res = requests.get(url)
            return res.text != ''
        except Exception as e:
            logging.debug(str(e))
            return False

    def should_visit(self, url):
        """ return url that should be visited, or None to skip this url
        """
        if '#' in url:
            url = url.split('#', 1)[0]

        if self.already_recorded(url):
            logging.debug('Skipping Dupe: ' + url)
            return None

        if self.auto.scopes:
            for scope in self.auto.scopes:
                if scope.search(url):
                    logging.debug('In scope: ' + scope.pattern)
                    return url

            return None

        return url

    def wait_queue(self):
        # reset to empty url to indicate previous page is done
        self.auto.tab_added(self.browser.reqid, self.tab_id, '')
        url_req_data = None
        url_req = None

        while self.browser.running:
            name, url_req_data = self.redis.blpop(self.browser_q)
            url_req = json.loads(url_req_data)

            url_req['url'] = self.should_visit(url_req['url'])
            if url_req['url']:
                break

        if not url_req:
            logging.debug('Browser Halted')
            return

        def save_frame(resp):
            frame_id = resp['result'].get('frameId')
            if frame_id:
                self.frame_id = frame_id

        try:
            logging.debug('Queuing Next: ' + str(url_req))

            self.hops = url_req.get('hops', 0)
            self.curr_url = url_req['url']

            self.send_ws({"method": "Page.navigate", "params": {"url": self.curr_url}},
                         save_frame)

            self.auto.tab_added(self.browser.reqid, self.tab_id, url_req['url'])

        except Exception as e:
            logging.error(' *** ' + str(e))
            if url_req_data:
                self.redis.rpush(self.browser_q, url_req_data)

    def recv_ws_loop(self):
        try:
            while self.browser.running:
                resp = self.ws.recv()
                resp = json.loads(resp)

                try:
                    if 'result' in resp and 'id' in resp:
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

    def load_links(self):
        #logging.debug('HOPS LEFT: ' + str(self.hops))
        if not self.hops:
            self.queue_next()
            return

        def handle_links(resp):
            links = json.loads(resp['result']['result']['value'])

            logging.debug('Links')
            logging.debug(str(links))

            for link in links:
                url_req = {'url': link}
                # set hops if >0
                if self.hops > 1:
                    url_req['hops'] = self.hops - 1

                self.redis.rpush(self.browser_q, json.dumps(url_req))

            self.queue_next()

        self.eval('JSON.stringify(window.extractLinks ? window.extractLinks() : [])', handle_links)

    def handle_result(self, resp):
        callback = self.callbacks.pop(resp['id'], None)
        if callback:
            try:
                callback(resp)
            except Exception as e:
                logging.debug(str(e))
        else:
            logging.debug('No Callback found for: ' + str(resp['id']))

    def handle_frameStoppedLoading(self, resp):
        frame_id = resp['params']['frameId']

        # ensure top-frame stopped loading
        if frame_id != self.frame_id:
            return

        # if not html, continue
        if self.curr_mime != 'text/html':
            self.queue_next()
            return

        if self.auto['autoscroll']:
            logging.debug('AutoScroll Start')
            self.browser.send_pubsub({'ws_type': 'autoscroll'})
        else:
            self.load_links()

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
            page = {'url': frame['url'],
                    'title': frame['url'],
                    'timestamp': self.cdata['request_ts'] or timestamp_now(),
                    'browser': self.cdata['browser'],
                   }

            self.auto.recording.add_page(page, False)

    def send_ws(self, data, callback=None):
        self.id_count += 1
        data['id'] = self.id_count
        if callback:
            self.callbacks[self.id_count] = callback

        self.ws.send(json.dumps(data))

    def eval(self, expr, callback=None):
        self.send_ws({"method": "Runtime.evaluate", "params": {"expression": expr}}, callback)

    def close(self):
        try:
            if self.ws:
                self.ws.close()

            self.auto.tab_removed(self.browser.reqid, self.tab_id)
        except:
            pass

        finally:
            self.ws = None


# ============================================================================
if __name__ == "__main__":
    AutoManager.main()
