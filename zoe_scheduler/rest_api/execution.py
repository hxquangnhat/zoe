# Copyright (c) 2016, Daniele Venzano
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from werkzeug.exceptions import BadRequest
from flask_restful import Resource, request

from zoe_lib.exceptions import ZoeException, ZoeRestAPIException
from zoe_scheduler.rest_api.utils import catch_exceptions
from zoe_scheduler.state.manager import StateManager
from zoe_scheduler.platform_manager import PlatformManager
from zoe_scheduler.state.execution import Execution
from zoe_scheduler.rest_api.auth.authentication import authenticate
from zoe_scheduler.rest_api.auth.authorization import is_authorized, check_quota


class ExecutionAPI(Resource):
    """
    :type state: StateManager
    :type platform: PlatformManager
    """
    def __init__(self, **kwargs):
        self.state = kwargs['state']
        self.platform = kwargs['platform']

    @catch_exceptions
    def get(self, execution_id):
        calling_user = authenticate(request, self.state)

        e = self.state.get_one('execution', id=execution_id)
        if e is None:
            raise ZoeRestAPIException('No such execution', 404)

        is_authorized(calling_user, e, 'get')
        ret = e.to_dict(checkpoint=False)

        return ret

    @catch_exceptions
    def delete(self, execution_id: int):
        """
        This method is called when a user wants to stop an execution. To actually delete the execution,
        the user has to delete the 'parent' application.
        :param execution_id: the execution to be deleted
        :return:
        """
        calling_user = authenticate(request, self.state)

        e = self.state.get_one('execution', id=execution_id)
        if e is None:
            raise ZoeRestAPIException('No such execution', 404)

        is_authorized(calling_user, e, 'delete')

        if e.status == "running" or e.status == "scheduled":
            self.platform.execution_terminate(e, reason='terminated')

        self.state.state_updated()

        return '', 204


class ExecutionCollectionAPI(Resource):
    """
    :type state: StateManager
    :type platform: PlatformManager
    """
    def __init__(self, **kwargs):
        self.state = kwargs['state']
        self.platform = kwargs['platform']

    @catch_exceptions
    def get(self):
        """
        Returns a list of all active executions.

        :return:
        """
        calling_user = authenticate(request, self.state)
        execs = self.state.get('execution')
        ret = []
        for e in execs:
            try:
                is_authorized(calling_user, e, "get")
            except ZoeRestAPIException:
                continue
            else:
                ret.append(e.to_dict(checkpoint=False))
        return ret

    @catch_exceptions
    def post(self):
        """
        Starts an execution, given an application_id. Takes a JSON object like this: { "application_id": 4 }
        :return: the new execution_id
        """
        calling_user = authenticate(request, self.state)

        try:
            data = request.get_json()
        except BadRequest:
            raise ZoeRestAPIException('Error decoding JSON data')

        execution = Execution(self.state)
        try:
            execution.from_dict(data, checkpoint=False)
        except ZoeException as e:
            raise ZoeRestAPIException(e.value)

#        if not zoe_sched_singleton.validate(execution.application):
#            return error('admission control refused this application description')

        is_authorized(calling_user, execution, 'create')
        check_quota(calling_user, self.state)

        execution.id = self.state.gen_id()
        self.state.new('execution', execution)

        self.platform.execution_submitted(execution)

        self.state.state_updated()

        return {'execution_id': execution.id}, 201