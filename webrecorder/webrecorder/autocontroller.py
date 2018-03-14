from webrecorder.basecontroller import BaseController
from webrecorder.models.auto import Auto
from bottle import request


# ============================================================================
class AutoController(BaseController):
    def init_routes(self):

        # CREATE AUTO
        @self.app.post('/api/v1/auto')
        def create_auto(self):
            user, collection = self.load_user_coll()

            aid = collection.create_auto()


        # QUEUE LIST + START
        @self.app.post('/api/v1/auto/<aid>/queue_list')
        def add_lists(self, aid):
            user, collection, auto = self.load_user_coll_auto(aid)

            list_id = request.json['list']

            result = auto.queue_list(list_id)
            if result:
                return {'error_message': result}

            auto.start()
            return {'status': auto['status']}


    def load_user_coll_auto(self, aid, user=None, coll_name=None):
        user, collection = self.load_user_coll(user=user, coll_name=coll_name)

        return user, collection, self.load_auto(collection, aid)

    def load_list(self, collection, aid):
        auto = collection.get_auto(aid)
        if not auto:
            self._raise_error(404, 'Automation not found', api=True,
                              id=aid)

        return auto




