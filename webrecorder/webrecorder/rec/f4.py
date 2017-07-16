import requests
from six.moves.urllib.parse import urlsplit, quote_plus
import os


# =============================================================================
class F4Storage(object):
    def __init__(self, config):
        self.remote_url_templ = config['remote_url_templ']

    def get_valid_remote_url(self, user, coll, rec, warcname):
        remote_url = self.remote_url_templ.format(user=user,
                                                  coll=coll,
                                                  rec=rec,
                                                  filename=warcname)

        if self._path_exists(remote_url):
            return remote_url
        else:
            return None

    def _path_exists(self, url):
        try:
            res = requests.head(url)
            res.raise_for_status()
        except Exception as e:
            print(e)
            return False

        return True

    def upload_file(self, user, coll, rec, warcname, full_filename):
        remote_url = self.remote_url_templ.format(user=user,
                                                  coll=coll,
                                                  rec=rec,
                                                  filename=warcname)

        filename = os.path.basename(warcname)

        headers = {'Content-Type': 'application/warc',
                   'Content-Disposition': 'attachment; filename="{0}"'.format(filename)
                  }

        try:
            print('Uploading {0} -> {1}'.format(full_filename, remote_url))
            with open(full_filename, 'rb') as fh:
                res = requests.put(remote_url, data=fh, headers=headers)
                res.raise_for_status()
        except Exception as e:
            print(e)
            print('Failed to Upload to {0}'.format(remote_url))
            return False

        return True

    def delete(self, delete_list):
        for remote_file in delete_list:
            try:
                res = requests.delete(remote_file)
                res.raise_for_status()
            except Exception as e:
                print(e)
                return False

        return True

    def delete_user(self, user):
        remote_url = self.remote_url_templ.format(user=user,
                                                  filename='')

        path_list = []

        for key in self.bucket.list(prefix=remote_path):
            path_list.append(key)
            print('Deleting ' + key.name)

        try:
            self.bucket.delete_keys(path_list)

        except Exception as e:
            print(e)
            return False

        return True

