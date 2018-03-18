from webrecorder.basecontroller import BaseController
from webrecorder.models.auto import Auto
from bottle import request


# ============================================================================
class AutoController(BaseController):
    def init_routes(self):

        # CREATE AUTO
        @self.app.post('/api/v1/auto')
        def create_auto():
            user, collection = self.load_user_coll()

            aid = collection.create_auto(request.json)

            return {'auto': aid}

        # QUEUE LIST + START
        @self.app.post('/api/v1/auto/<aid>/queue_list')
        def add_lists(aid):
            user, collection, auto = self.load_user_coll_auto(aid)

            list_id = request.json['list']

            result = auto.queue_list(list_id)
            if result:
                return {'error_message': result}

            auto.start()
            return {'status': auto['status']}

        # GET AUTO
        @self.app.get('/api/v1/auto/<aid>')
        def get_auto(aid):
            user, collection, auto = self.load_user_coll_auto(aid)

            self.access.assert_can_admin_coll(collection)

            return {'auto': auto.serialize()}

        # DELETE AUTO
        @self.app.delete('/api/v1/auto/<aid>')
        def delete_auto(aid):
            user, collection, auto = self.load_user_coll_auto(aid)

            auto.delete_me()

            return {'deleted_id': auto.my_id}

    def load_user_coll_auto(self, aid, user=None, coll_name=None):
        user, collection = self.load_user_coll(user=user, coll_name=coll_name)

        return user, collection, self.load_auto(collection, aid)

    def load_auto(self, collection, aid):
        auto = collection.get_auto(aid)
        if not auto:
            self._raise_error(404, 'Automation not found', api=True,
                              id=aid)

        return auto




